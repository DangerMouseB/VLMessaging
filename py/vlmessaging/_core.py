# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************


# Router is responsible for routing messages between local connections and / or other routers in other local and / or
# remote. Local routing does not require serialisation, cross process / cross machine routing does.
# if nng's ipc transport is faster than its tcp transport then the router should use it in the background

# if we want this router to publish agents in the directory then it must have two listener sockets, one (ipc based) for
# local agents from this smachine, and another (tcp based) for remote agents on other machines. These sockets can be
# created lazily whenever an agent advertises itself. The local directory name shall be "ipc:///tmp/local_dir.ipc"

# threading design
# each daemon with a connection is on its own thread - so preemptive (albeit single threaded at the interpreter level)
# we want the router itself to be non-blocking so use Python's async methods
# we may put resource discovery into the router thread
# pubsub will be sent via a socket rather than locally

# every router needs to be connected to the directory daemon so we can build the network on an adhoc basis
# before a router can listener it must get an address from the directory
# directory can heartbeat - hopefully GIL won't delay heartbeat intervals significant

# need a directory -
# dial the directory, if refused, launch a directory process, if starting up and get Address in use abandon startup

# ASSUMPTIONS
# - resources to do inter-machine communication are scarcer (e.g. ports), intra-machine resources are plentiful

# INTERMACHINE TOPOLOGY
# 2 options:
# 1. any router can connect to another machine - each listener requires a port
#    - 1 hop messaging but harder to do firewall rules
# 2. one router per machine connects to other machines - just one listener per machine
#    - easier to do firewall rules, but 1-3 hop messaging (depends if sender and receiver are on the main router or not)
#    - harder to use multicast scalability protocols
# OPEN:
# - easier to do security at the central router?
# - could mix the two approaches - since cross machine services are less common

# ipc:///tmp/directory
# ipc:///tmp/agent1
# ipc:///tmp/agent2


# Python imports
import itertools, io, logging, pynng, asyncio
from amazon.ion import simpleion

# coppertop imports
from coppertop.utils import Missing, NotYetImplemented, ProgrammerError

# local imports
from vlmessaging._structs import Addr, Msg, Entry


_logger = logging.getLogger(__name__)


PUB = None
LOCAL_DIRECTORY = Addr('LOCAL_DIRECTORY', -1)
REMOTE_DIRECTORY = Addr('REMOTE_DIRECTORY', -1)

DIRECTORY_ADDR = "ipc:///tmp/directory"
DIRECTORY_CONNECTION_ID = 1
_SERVICE_ADDR_PREFIX = "ipc:///tmp/service_"
DIRECTORY_CHECK_INTERVAL = 5000  # seconds

addr = "tcp://127.0.0.1:13134"

INVALID_ADDRESS = 'INVALID_ADDRESS'
REGISTER_SERVICE = 'REGISTER_SERVICE'
REGISTER_SERVICE_REPLY = 'REGISTER_SERVICE_REPLY'
UNREGISTER_SERVICE = 'UNREGISTER_SERVICE'
UNREGISTER_SERVICE_REPLY = 'UNREGISTER_SERVICE_REPLY'
SERVICE_NOT_LISTENING = 'SERVICE_NOT_LISTENING'
GET_SERVICES = 'GET_SERVICES'
GET_SERVICES_REPLY = 'GET_SERVICES_REPLY'

HEARTBEAT = 'HEARTBEAT'
HEARTBEAT_REPLY = 'HEARTBEAT_REPLY'

GET_AGENT_ID = 'GET_AGENT_ID'
GET_AGENT_ID_REPLY = 'GET_AGENT_ID_REPLY'
CLOSING_AGENT = 'CLOSING_AGENT'

UNKNOWN_SUBJECT = 'UNKNOWN_SUBJECT'



class Connection:

    __slots__ = ('_router', '_msgArrivedFn', '_inbox', '_futureByReplyId', '_msgIdSeed', 'addr')

    def __init__(self, router, connectionId, fn):
        self._router = router
        self._msgArrivedFn = fn
        self._inbox = asyncio.Queue()
        self._futureByReplyId = {}
        self._msgIdSeed = itertools.count(1)
        self.addr = Addr(Missing, connectionId)

    async def _deliver(self, msg):
        if (fut := self._futureByReplyId.pop(msg._replyId, Missing)) is Missing:
            # no future waiting for this reply so just pass it to the handler
            printMsg(f'deliver msg', msg._msgId)
            await self._msgArrivedFn(msg)
        else:
            # we have a future waiting for this reply
            if fut.done():
                # is this possible?
                pass
            else:
                # we have the reply in time so pass it to the future
                printMsg(f'deliver reply', msg._msgId)
                fut.set_result(msg)

    async def send(self, msg, timeout=Missing):
        # return reply, Missing if timeout exceeded or None if no timeout
        msg._msgId = next(self._msgIdSeed)
        msg.fromAddr = self.addr
        if timeout:
            # semi-sync send - wait for reply or timeout
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            self._futureByReplyId[msg._msgId] = fut
            printMsg(f'send({timeout})', msg)
            asyncio.create_task(self._router._route(msg))
            try:
                reply = await asyncio.wait_for(fut, timeout / 1000)
            except asyncio.TimeoutError:
                printMsg(f'TIMED OUT', msg)
                reply = Missing
            self._futureByReplyId.pop(msg._msgId, None)
            return reply
        else:
            # async send
            printMsg('send', msg)
            asyncio.create_task(self._router._route(msg))
            return None


class Router:

    __slots__ = (
        '_sDirectoryListener', '_sDirectory',                           # local directory connections
        '_sLocalPeerListener', '_localPipeByAddr', '_sLocalByAddr',     # local peer connections
        '_sRemotePeerListener', '_remotePipeByAddr', '_sRemoteByAddr',  # remote peer connections
        '_connectionsById', '_connectionIdSeed',
        '_entries'
    )

    def __init__(self):
        self._sDirectoryListener, self._sDirectory = Missing, Missing
        self._sLocalPeerListener, self._localPipeByAddr, self._sLocalByAddr = Missing, {}, {}
        self._sRemotePeerListener, self._remotePipeByAddr, self._sRemoteByAddr = Missing, {}, Missing
        self._connectionsById, self._connectionIdSeed = {}, itertools.count(1)
        self._entries = {}
        asyncio.create_task(self.start())

    def newConnection(self, fn):
        connectionId = next(self._connectionIdSeed)
        c = Connection(self, connectionId, fn)
        self._connectionsById[connectionId] = c
        return c

    async def _route(self, msg):
        printMsg(f'route', msg._msgId)
        self._connectionsById[msg.toAddr.connectionId]._inbox.put_nowait(msg)

    async def start(self):
        connIdByTask = {}
        while True:
            if len(connIdByTask) != len(self._connectionsById):
                for connectionId, conn in self._connectionsById.items():
                    if connectionId not in connIdByTask.values():
                        connIdByTask[asyncio.create_task(conn._inbox.get())] = connectionId
            if connIdByTask:
                done, pending = await asyncio.wait(connIdByTask.keys(), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    connectionId = connIdByTask.pop(task)
                    msg = task.result()
                    if (conn := self._connectionsById.get(connectionId, Missing)) is not Missing:
                        asyncio.create_task(conn._deliver(msg))
                        # Immediately start a new task for this connection
                        connIdByTask[asyncio.create_task(conn._inbox.get())] = connectionId
            else:
                await asyncio.sleep(0)

    async def tryStartDirectory(self):
        # try to start the directory here - potentially in a race with other processes
        if self._sDirectoryListener is not Missing: raise ProgrammerError('Already started as a directory')
        if self._sDirectory is not Missing: raise ProgrammerError('Already connected to the local directory')
        sock = pynng.Pair1(polyamorous=True)
        try:
            async with trio.open_nursery() as n:
                sock.add_pre_pipe_connect_cb(self.pre_connect_to_directory)
                sock.add_post_pipe_remove_cb(self.post_remove_from_directory)
                sock.listen(DIRECTORY_ADDR)
                n.start_soon(self.dispatch_from_ipc_socket, sock)
                n.start_soon(self.dispatch_msgs_in_queue, sock)
        except Exception as ex:
            sock.close()
            sock = Missing
        if sock is not Missing:
            self._sDirectoryListener = sock

    async def connectToDirectory(self):
        while True:
            if self._sDirectory is not Missing:
                # connected
                if len(self._sDirectory.pipes) == 1:
                    await trio.sleep(DIRECTORY_CHECK_INTERVAL / 1000)       # check again later
                    continue
                else:
                    self._sDirectory.close()
                    self._sDirectory = Missing
            else:
                # not connected, try to connect
                sock = pynng.Pair1(polyamorous=True)
                try:
                    sock.add_pre_pipe_connect_cb(self.pre_connect_to_directory)
                    sock.add_post_pipe_remove_cb(self.post_remove_from_directory)
                    sock.dial(DIRECTORY_ADDR)
                    self._sDirectory = sock
                    print("Connected to directory.")
                    async with trio.open_nursery() as n:
                        n.start_soon(self.dispatch_from_ipc_socket, sock)
                        n.start_soon(self.dispatch_msgs_in_queue, sock)
                        while True:
                            await trio.sleep(5)
                            # Check if connection is still alive
                            if not sock.pipes:
                                print("Lost connection to directory, reconnecting...")
                                break
                except Exception as ex:
                    print(f"Failed to connect to directory: {ex}")
                finally:
                    sock.close()
                    self._sDirectory = Missing
                    await trio.sleep(5)  # Wait before retrying

    async def startPeerListener(self, addr):
        self.sPeerListener = pynng.Pair1(polyamorous=True)
        async with trio.open_nursery() as n:

            self.sListen.add_pre_pipe_connect_cb(self.pre_connect_cb)
            self.sListen.add_post_pipe_remove_cb(self.post_remove_cb)
            self.sListen.listen(addr)
            n.start_soon(self.dispatch_from_ipc_socket, self.sListen)
            n.start_soon(self.dispatch_msgs_in_queue, self.sListen)

    def pre_connect_peer(self, pipe):
        print(f"~~~~got connection from {pipe.remote_address}")

    def post_remove_peer(self, pipe):
        print(f"~~~~goodbye for now from {pipe.remote_address}")

    def pre_connect_to_directory(self, pipe):
        print(f"~~~~got connection from {pipe.remote_address}")

    def post_remove_from_directory(self, pipe):
        print(f"~~~~goodbye for now from {pipe.remote_address}")


    async def start_agent(self, addr):
        with pynng.Pair1(polyamorous=True) as sock:
            async with trio.open_nursery() as n:
                sock.dial(addr)
                sock.fred = False
                n.start_soon(self.dispatch_from_ipc_socket, sock)
                n.start_soon(self.dispatch_msgs_in_queue, sock)

    async def dispatch_from_ipc_socket(self, sock):
        while True:
            msg = await sock.arecv_msg()
            # dispatch
            source_addr = str(msg.pipe.remote_address)
            content = msg.bytes.decode()
            print(f'{source_addr} says: {content}')
            if sock.fred:
                await msg.pipe.asend(f'got {content}'.encode())

    async def dispatch_msgs_in_queue(self, sock):
        while True:
            # wait for msgs to arrive in queue here
            stuff = await run_sync(input)  # , cancellable=True)
            # dispatch - inproc or ipc
            for pipe in sock.pipes:
                await pipe.asend(stuff.encode())

    def newConnection(self, msgArrivedFn) -> Connection:
        connId = next(self._connectionIdSeed)
        answer = Connection(self, connId, msgArrivedFn)
        self._connectionsById[connId] = answer
        return answer

    def _send(self, msg, timeout=Missing) -> Msg | Missing:
        # if timeout is Missing send asynchronously
        if msg.toAddr == PUB:
            # broadcast on the connection's pubsub socket
            raise NotYetImplemented()
        else:
            if msg.toAddr.socketAddr == LOCAL_DIRECTORY:
                if not self._localDirSocket:
                    # try connecting to local dir
                    # if can't be dialled try creating local directory
                    raise NotYetImplemented()
                raise NotYetImplemented()
            raise NotYetImplemented()


def _msgAsBytes(msg):
    bytes = io.BytesIO()
    simpleion.dump('1', bytes, binary=True)
    simpleion.dump(msg.fromAddr.socketAddr, bytes, binary=True)
    simpleion.dump(msg.fromAddr.connId, bytes, binary=True)
    if msg.toAddr == PUB:
        simpleion.dump(None, bytes, binary=True)
        simpleion.dump(None, bytes, binary=True)
    else:
        simpleion.dump(msg.toAddr.socketAddr, bytes, binary=True)
        simpleion.dump(msg.toAddr.connId, bytes, binary=True)
    simpleion.dump(msg.subject, bytes, binary=True)
    simpleion.dump(msg._msgId, bytes, binary=True)
    simpleion.dump(msg._replyId, bytes, binary=True)
    simpleion.dump(msg.contents, bytes, binary=True)
    simpleion.dump(msg.meta, bytes, binary=True)
    return bytes.getvalue()

def _msgFromBytes(bytes):
    values = simpleion.load(io.BytesIO(bytes), single_value=False)
    schema, fromAddrSocketAddr, fromAddrConnId, toAddrSocketAddr, toAddrConnId, subject, _msgId, _replyId, contents, meta = values
    schema = str(schema)
    fromAddrSocketAddr = str(fromAddrSocketAddr)
    fromAddrConnId = int(fromAddrConnId)
    toAddrSocketAddr = str(toAddrSocketAddr)
    toAddrConnId = int(toAddrConnId)
    subject = str(subject)
    _msgId = int(_msgId)
    _replyId = int(_replyId) if _replyId else None
    assert schema == '1'
    if toAddrSocketAddr:
        msg = Msg(Addr(toAddrSocketAddr, toAddrConnId), subject, contents)
    else:
        msg = Msg(PUB, subject, contents)
    msg.fromAddr = Addr(fromAddrSocketAddr, fromAddrConnId)
    msg._msgId = _msgId
    msg._replyId = _replyId
    msg.meta = meta
    # OPEN: assert stream at end
    return msg

def printMsg(prefix, msg):
    print(f'{prefix + ":":<14} {msg}')
