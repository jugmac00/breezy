# Copyright (C) 2006 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Souk: smart-server protocol.

Requests are sent as a command and list of arguments, followed by optional
bulk body data.  Responses are similarly a response and list of arguments,
followed by bulk body data. ::

  SEP := '\001'
    Fields are separated by Ctrl-A.
  BULK_DATA := CHUNK+ TRAILER
    Chunks can be repeated as many times as necessary.
  CHUNK := CHUNK_LEN CHUNK_BODY
  CHUNK_LEN := DIGIT+ NEWLINE
    Gives the number of bytes in the following chunk.
  CHUNK_BODY := BYTE[chunk_len]
  TRAILER := SUCCESS_TRAILER | ERROR_TRAILER
  SUCCESS_TRAILER := 'done' NEWLINE
  ERROR_TRAILER := 

"""



# TODO: A plain integer from query_version is too simple; should give some
# capabilities too?

# TODO: Server should probably catch exceptions within itself and send them
# back across the network.  (But shouldn't catch KeyboardInterrupt etc)
# Also needs to somehow report protocol errors like bad requests.  Need to
# consider how we'll handle error reporting, e.g. if we get halfway through a
# bulk transfer and then something goes wrong.

# TODO: Standard marker at start of request/response lines?

# TODO: Client and server warnings perhaps should contain some non-ascii bytes
# to make sure the channel can carry them without trouble?  Test for this?
#
# TODO: get/put objects could be changed to gradually read back the data as it
# comes across the network
#
# TODO: What should the server do if it hits an error and has to terminate?
#
# TODO: is it useful to allow multiple chunks in the bulk data?
#
# TODO: If we get an exception during transmission of bulk data we can't just
# emit the exception because it won't be seen.
#
# TODO: Clone method on Transport; should work up towards parent directory;
# unclear how this should be stored or communicated to the server... maybe
# just pass it on all relevant requests?
#
# TODO: Better name than clone() for changing between directories.  How about
# open_dir or change_dir or chdir?
#
# TODO: Is it really good to have the notion of current directory within the
# connection?  Perhaps all Transports should factor out a common connection
# from the thing that has the directory context?
#
# TODO: Pull more things common to sftp and ssh to a higher level.
#
# TODO: The server that manages a connection should be quite small and retain
# minimum state because each of the requests are supposed to be stateless.
# Then we can write another implementation that maps to http.
#
# TODO: What to do when a client connection is garbage collected?  Maybe just
# abruptly drop the connection?
#
# TODO: Server in some cases will need to restrict access to files outside of
# a particular root directory.
#
# TODO: Handle close for tcp and stream clients.


from cStringIO import StringIO
import errno
import os
import socket
import sys
import threading

from bzrlib import errors, transport
from bzrlib.transport import sftp, local


# must do this otherwise we can't parse the urls properly
for scheme in ['ssh', 'bzr', 'bzr+loopback']:
    transport.register_urlparse_netloc_protocol(scheme)
del scheme


class BzrProtocolError(errors.TransportError):
    pass


def _recv_tuple(from_file):
    req_line = from_file.readline()
    if req_line == None or req_line == '':
        return None
    if req_line[-1] != '\n':
        raise BzrProtocolError("request %r not terminated" % req_line)
    return tuple((a.decode('utf-8') for a in req_line[:-1].split('\1')))


def _send_tuple(to_file, args):
    to_file.write('\1'.join((a.encode('utf-8') for a in args)) + '\n')
    to_file.flush()


def _recv_bulk(from_file):
    chunk_len = from_file.readline()
    try:
        chunk_len = int(chunk_len)
    except ValueError:
        raise BzrProtocolError("bad chunk length line %r" % chunk_len)
    bulk = from_file.read(chunk_len)
    if len(bulk) != chunk_len:
        raise BzrProtocolError("short read fetching bulk data chunk")
    return bulk


class SoukStreamServer(object):
    """Handles souk commands coming over a stream.

    The stream may be a pipe connected to sshd, or a tcp socket, or an
    in-process fifo for testing.

    One instance is created for each connected client; it can serve multiple
    requests in the lifetime of the connection.

    The server passes requests through to an underlying backing transport, 
    which will typically be a LocalTransport looking at the server's filesystem.
    """

    def __init__(self, in_file, out_file, backing_transport):
        """Construct new server.

        :param in_file: Python file from which requests can be read.
        :param out_file: Python file to write responses.
        :param backing_transport: Transport for the directory served.
        """
        self._in = in_file
        self._out = out_file
        self._backing_transport = backing_transport

    def _do_query_version(self):
        """Answer a version request with my version."""
        self._send_tuple(('bzr server', '1'))

    def _do_has(self, relpath):
        r = self._backing_transport.has(relpath) and 'yes' or 'no'
        self._send_tuple((r,))

    def _do_get(self, relpath):
        backing_file = self._backing_transport.get(relpath)
        self._send_tuple(('ok', ))
        self._send_bulk_data(backing_file.read())

    def serve(self):
        """Serve requests until the client disconnects."""
        try:
            while self._serve_one_request() != False:
                pass
        except Exception, e:
            self._report_error("%s terminating on exception %s" % (self, e))
            raise

    def _report_error(self, msg):
        sys.stderr.write(msg + '\n')
        
    def _serve_one_request(self):
        """Read one request from input, process, send back a response.
        
        :return: False if the server should terminate, otherwise None.
        """
        req_args = self._recv_tuple()
        if req_args == None:
            # client closed connection
            return False  # shutdown server
        try:
            self._dispatch_command(req_args[0], req_args[1:])
        except errors.NoSuchFile, e:
            self._send_tuple(('enoent', e.path))
        except KeyboardInterrupt:
            raise
        except Exception, e:
            # everything else: pass to client, flush, and quit
            self._send_error_and_disconnect(e)
            return False

    def _send_error_and_disconnect(self, exception):
        self._send_tuple(('error', str(exception)))
        self._out.flush()
        self._out.close()
        self._in.close()

    def _dispatch_command(self, cmd, args):
        if cmd == 'hello':
            self._do_query_version()
        elif cmd == 'has':
            self._do_has(*args)
        elif cmd == 'get':
            self._do_get(*args)
        else:
            raise BzrProtocolError("bad request %r" % (cmd,))

    def _recv_tuple(self):
        """Read a request from the client and return as a tuple.
        
        Returns None at end of file (if the client closed the connection.)
        """
        return _recv_tuple(self._in)

    def _send_tuple(self, args):
        """Send response header"""
        return _send_tuple(self._out, args)

    def _send_bulk_data(self, body):
        """Send chunked body data"""
        assert isinstance(body, str)
        self._out.write('%d\n' % len(body))
        self._out.write(body)
        self._out.write('done\n')
        self._out.flush()


class SoukTCPServer(object):
    """Listens on a TCP socket and accepts connections from souk clients"""

    def __init__(self, backing_transport=None):
        if backing_transport is None:
            backing_transport = memory.MemoryTransport()
        self._server_socket = socket.socket()
        self._server_socket.bind(('127.0.0.1', 0))
        self._server_socket.listen(1)
        self._server_socket.settimeout(0.2)
        self.backing_transport = backing_transport

    def serve_until_stopped(self):
        # let connections timeout so that we get a chance to terminate
        while not self._should_terminate:
            self.accept_and_serve()

    def get_url(self):
        """Return the url of the server"""
        return "bzr://%s:%d/" % self._server_socket.getsockname()

    def accept_and_serve(self):
        conn, client_addr = self._server_socket.accept()
        from_client = conn.makefile('r')
        to_client = conn.makefile('w')
        handler = SoukStreamServer(from_client, to_client,
                self.backing_transport)
        handler.serve()

    def start_background_thread(self):
        self._should_terminate = False
        self._server_thread = threading.Thread(None,
                self.serve_until_stopped,
                name='server-' + self.get_url())
        self._server_thread.setDaemon(True)
        self._server_thread.start()

    def stop_background_thread(self):
        self._should_terminate = True
        self._server_socket.close()
        # we used to join the thread, but it's not really necessary; it will
        # terminate in time
        ## self._server_thread.join()


class SoukTCPServer_for_testing(SoukTCPServer):
    """Server suitable for use by transport tests.
    
    This server is backed by the process's cwd.
    """

    def __init__(self):
        self._homedir = os.getcwd()
        SoukTCPServer.__init__(self, transport.get_transport(self._homedir))
        
    def setUp(self):
        """Set up server for testing"""
        self.start_background_thread()

    def tearDown(self):
        self.stop_background_thread()

    def get_url(self):
        """Return the url of the server"""
        host, port = self._server_socket.getsockname()
        return "bzr://%s:%d/%s" % (host, port, self._homedir)

    def get_bogus_url(self):
        """Return a URL which will fail to connect"""
        return 'bzr://127.0.0.1:1/'


class SoukTransport(sftp.SFTPUrlHandling):
    """Connection to a souk server.

    The connection holds references to pipes that can be used to send requests
    to the server.

    The connection has a notion of the current directory to which it's
    connected; this is incorporated in filenames passed to the server.
    
    This supports some higher-level RPC operations and can also be treated 
    like a Transport to do file-like operations.

    The connection can be made over a tcp socket, or (in future) an ssh pipe
    or a series of http requests.  There are concrete subclasses for each
    type: SoukTCPClient, etc.
    """

    def __init__(self, server_url, clone_from=None):
        super(SoukTransport, self).__init__(server_url)
        if clone_from is None:
            self._connect_to_server()
        else:
            # reuse same connection
            self._to_server = clone_from._to_server
            self._from_server = clone_from._from_server

    def clone(self, relative_url):
        """Make a new SoukTransport related to me, sharing the same connection.

        This essentially opens a handle on a different remote directory.
        """
        return SoukTransport(self.abspath(relative_url), self)

    def is_readonly(self):
        """Souk protocol currently only supports readonly operations."""
        return True
    
    def query_version(self):
        """Return protocol version number of the server."""
        # XXX: should make sure it's empty
        self._send_tuple(('hello', '1'))
        resp = self._recv_tuple()
        if resp == ('bzr server', '1'):
            return 1
        else:
            raise BzrProtocolError("bad response %r" % (resp,))
        
    def has(self, relpath):
        resp = self._call('has', self._remote_path(relpath))
        if resp == ('yes', ):
            return True
        elif resp == ('no', ):
            return False
        else:
            self._translate_error(resp)

    def get(self, relpath):
        """Return file-like object reading the contents of a remote file."""
        resp = self._call('get', self._remote_path(relpath))
        if resp != ('ok', ):
            self._translate_error(resp)
        body = self._recv_bulk()
        self._recv_trailer()
        return StringIO(body)

    def _recv_trailer(self):
        resp = self._recv_tuple()
        if resp == ('done', ):
            return
        else:
            self._translate_error(resp)

    def _call(self, *args):
        self._send_tuple(args)
        return self._recv_tuple()

    def _translate_error(self, resp):
        """Raise an exception from a response"""
        what = resp[0]
        if what == 'enoent':
            raise errors.NoSuchFile(resp[1])
        else:
            raise BzrProtocolError('bad trailer on get: %r' % (resp,))

    def _recv_bulk(self):
        return _recv_bulk(self._from_server)

    def _send_tuple(self, args):
        _send_tuple(self._to_server, args)

    def _recv_tuple(self):
        return _recv_tuple(self._from_server)

    def disconnect(self):
        self._to_server.close()
        self._from_server.close()

    def append(self, relpath, from_file):
        raise errors.TransportNotPossible("writing to souk servers not supported yet")

    def delete(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def delete_tree(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def put(self, relpath, f, mode=None):
        raise errors.TransportNotPossible('readonly transport')

    def mkdir(self, relpath, mode=None):
        raise errors.TransportNotPossible('readonly transport')

    def rmdir(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def stat(self, relpath):
        raise errors.TransportNotPossible('souk does not support stat()')

    def lock_write(self, relpath):
        raise errors.TransportNotPossible('readonly transport')

    def listable(self):
        return False

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock()
        """
        # The old RemoteBranch ignore lock for reading, so we will
        # continue that tradition and return a bogus lock object.
        class BogusLock(object):
            def __init__(self, path):
                self.path = path
            def unlock(self):
                pass
        return BogusLock(relpath)


class SoukStreamClient(SoukTransport):
    """Connection to smart server over externally provided fifos"""
    def __init__(self, from_server, to_server):
        ## super(SoukTCPClient, self).__init__('bzr://<pipe>/')
        self.base = 'bzr://<pipe>/'
        self._from_server = from_server
        self._to_server = to_server


class SoukTCPClient(SoukTransport):
    """Connection to smart server over plain tcp"""

    def __init__(self, url):
        super(SoukTCPClient, self).__init__(url)
        self._scheme, self._username, self._password, self._host, self._port, self._path = \
                transport.split_url(url)

    def _connect_to_server(self):
        self._socket = socket.socket()
        result = self._socket.connect_ex((self._host, self._port))
        if result:
            raise errors.ConnectionError("failed to connect to %s:%d: %s" %
                    (self._host, self._port, os.strerror(result)))
        # TODO: May be more efficient to just treat them as sockets
        # throughout?  But what about pipes to ssh?...
        self._to_server = self._socket.makefile('w')
        self._from_server = self._socket.makefile('r')

    def disconnect(self):
        super(SoukTCPClient, self).disconnect()
        self._socket.close()


class LoopbackSoukConnection(SoukTransport):
    """Souk server talking over pipe within process for testing.

    It just connects together the ssh client and server, and creates
    a server for us just like running ssh will.

    This hides from the caller the details of setting up a transport, etc.  

    :ivar backing_transport: The transport used by the real server.
    """

    def __init__(self, backing_transport=None):
        if backing_transport is None:
            from bzrlib.transport import memory
            backing_transport = memory.MemoryTransport('memory:///')
        self.backing_transport = backing_transport
        super(LoopbackSoukConnection, self).__init__('bzr+loopback://localhost/')

    def _connect_to_server(self):
        import threading
        from_client_fd, to_server_fd = os.pipe()
        from_server_fd, to_client_fd = os.pipe()
        self._to_server = os.fdopen(to_server_fd, 'wb')
        self._from_server = os.fdopen(from_server_fd, 'rb')
        self._server = SoukStreamServer(os.fdopen(from_client_fd, 'rb'),
                                        os.fdopen(to_client_fd, 'wb'),
                                        self.backing_transport)
        self._server_thread = threading.Thread(None,
                self._server.serve,
                name='loopback-bzr-server-%x' % id(self._server))
        self._server_thread.setDaemon(True)
        self._server_thread.start()


def get_test_permutations():
    """Return (transport, server) permutations for testing"""
    return [(SoukTCPClient, SoukTCPServer_for_testing)]
