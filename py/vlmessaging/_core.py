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
# local agents from this machine, and another (tcp based) for remote agents on other machines. These sockets can be
# created lazily whenever an agent advertises itself. The local directory name shall be "ipc:///tmp/local_dir.ipc"

# threading design
# each daemon with a connection is on its own thread - so preemptive (albeit single threaded at the interpreter level)
# we want the router itself to be non-blocking so use Python's async methods
# pubsub will be sent via a socket rather than locally

# every router needs to be connected to the directory daemon so we can build the network on an adhoc basis
# before a router can listener it must get an address from the directory
# directory can heartbeat - hopefully GIL won't delay heartbeat intervals significant
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


# VLM.DIRECTORY should be a logical address where you can find out everything you may need to know about services
# available. Physically if it is a local directory, an isolated machine one or a machine one connected to other
# machines is a matter of configuration. Ultimately we could do virtual networks and bridge between them but that is
# for another day. Also authentication and authorisation should be built in from the ground up and will affect the
# experience a given agent has of the world around it.



# Python imports
import itertools, io, logging, pynng, asyncio, weakref
from amazon.ion import simpleion

# coppertop imports
from coppertop.utils import Missing, NotYetImplemented, ProgrammerError

# local imports
from vlmessaging._structs import Addr, Msg
from vlmessaging import _constants as VLM


_logger = logging.getLogger(__name__)

class ExitMessageHandler(Exception): pass


# **********************************************************************************************************************
# Connection
# **********************************************************************************************************************

class Connection:

    __slots__ = ('_router', '_msgArrivedFn', '_futureByReplyId', '_msgIdSeed', 'addr', '__weakref__')

    def __init__(self, router, connectionId, fn):
        self._router = router
        self._msgArrivedFn = fn
        self._futureByReplyId = {}
        self._msgIdSeed = itertools.count(1)
        self.addr = Addr(VLM.LOCAL, connectionId)

    async def _deliver(self, msg):
        if (fut := self._futureByReplyId.pop(msg._replyId, Missing)) is Missing:
            if self._msgArrivedFn:
                # no future waiting for this reply so just pass it to the handler
                _PPMsg(f'deliver msg', msg._msgId)
                try:
                    res = await self._msgArrivedFn(msg)
                    if res is None:
                        pass
                    else:
                        if isinstance(res, str): res = [str]
                        handled = False
                        for instruction in res:
                            if instruction == VLM.IGNORE_UNHANDLED_REPLIES:
                                if msg.subject.endswith('_REPLY'):
                                    handled = True
                                    break
                            elif instruction == VLM.HANDLE_DOES_NOT_UNDERSTAND:
                                if msg.subject == VLM.DOES_NOT_UNDERSTAND:
                                    handled = True
                                else:
                                    _PPMsg(f'UNHANDLED SUBJECT', msg)
                                    await self.send(msg.reply(VLM.DOES_NOT_UNDERSTAND, msg.subject))
                                    handled = True
                            else:
                                raise SyntaxError(f'Unknown instruction "{msg.subject}".')
                        if not handled:
                            _PPMsg(f'UNHANDLED SUBJECT', msg)
                except ExitMessageHandler as ex:
                    pass
            else:
                # no handler so reply it wasn't delivered
                _PPMsg(f'undeliverable', msg._msgId)
                await self.send(msg.reply(VLM.MSG_NOT_DELIVERED, msg.toAddr))
        else:
            # we have a future waiting for this reply
            if fut.done():
                # is this possible?
                pass
            else:
                # we have the reply in time so pass it to the future
                _PPMsg(f'deliver reply', msg._msgId)
                fut.set_result(msg)

    # def _send(self, msg, timeout=Missing) -> Msg | Missing:
    #     # if timeout is Missing send asynchronously
    #     if msg.toAddr == VLM.PUB:
    #         # broadcast on the connection's pubsub socket
    #         raise NotYetImplemented()
    #     else:
    #         if msg.toAddr.socketAddr == DIRECTORY:
    #             if not self._localDirSocket:
    #                 # try connecting to local dir
    #                 # if can't be dialled try creating local directory
    #                 raise NotYetImplemented()
    #             raise NotYetImplemented()
    #         raise NotYetImplemented()

    async def send(self, msg, timeout=Missing):
        # return reply, Missing if timeout exceeded or None if no timeout
        msg._msgId = next(self._msgIdSeed)
        msg.fromAddr = self.addr
        if timeout:
            # semi-sync send - wait for reply or timeout
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            self._futureByReplyId[msg._msgId] = fut
            _PPMsg(f'send({timeout})', msg)
            self._router._route(msg)
            try:
                reply = await asyncio.wait_for(fut, timeout / 1000)
            except asyncio.TimeoutError:
                _PPMsg(f'TIMED OUT', msg)
                reply = Missing
            self._futureByReplyId.pop(msg._msgId, None)
            return reply
        else:
            # async send
            _PPMsg('send', msg)
            self._router._route(msg)
            return None

    def __del__(self):
        # clean up any pending futures
        for fut in self._futureByReplyId.values():
            if not fut.done():
                fut.set_result(Missing)
        # tell router
        self._router._dropInboxFor(self.addr.connectionId)



# **********************************************************************************************************************
# Router
# **********************************************************************************************************************

class Router:

    __slots__ = (
        '_sDirectoryListener', '_sDirectory',                           # local directory connections
        '_sLocalPeerListener', '_localPipeByAddr', '_sLocalByAddr',     # local peer connections
        '_sRemotePeerListener', '_remotePipeByAddr', '_sRemoteByAddr',  # remote peer connections
        '_connectionById', '_inboxById',
        '_connectionIdSeed', '_refreshInboxTasks',
        '_entries',
        '_closingDown',
    )

    def __init__(self):
        self._sDirectoryListener, self._sDirectory = Missing, Missing
        self._sLocalPeerListener, self._localPipeByAddr, self._sLocalByAddr = Missing, {}, {}
        self._sRemotePeerListener, self._remotePipeByAddr, self._sRemoteByAddr = Missing, {}, Missing
        self._connectionById , self._inboxById = weakref.WeakValueDictionary(), {}
        self._connectionIdSeed, self._refreshInboxTasks = itertools.count(VLM.DIRECTORY_CONNECTION_ID + 1), False
        self._entries = {}
        asyncio.create_task(self._processInboxes())
        self._closingDown = asyncio.Event()

    def newConnection(self, fn=Missing):
        return self._newConnection(next(self._connectionIdSeed), fn)

    def _newConnection(self, connectionId, fn):
        c = Connection(self, connectionId, fn)
        assert connectionId not in self._connectionById
        self._connectionById[connectionId] = c
        self._inboxById[connectionId] = asyncio.Queue()
        self._refreshInboxTasks = True
        return c

    async def shutdown(self):
        self._connectionById = {}
        self._closingDown.set()
        await asyncio.sleep(0.01)  # do this here so the client doesn't have to - annoyingly we can't loop until done

    def _dropInboxFor(self, connectionId):
        self._inboxById.pop(connectionId, None)
        self._refreshInboxTasks = True

    def _route(self, msg):
        routerId, cid = msg.toAddr
        if routerId == VLM.LOCAL:
            conn = self._connectionById.get(cid, Missing)
            if conn:
                _PPMsg(f'route', msg._msgId)
                self._inboxById[cid].put_nowait(msg)
            else:
                if msg.subject == VLM.MSG_NOT_DELIVERED:
                    # don't get into a loop of undeliverable messages
                    pass
                else:
                    reply = msg.reply(VLM.MSG_NOT_DELIVERED, msg.toAddr)
                    reply._msgId = -1
                    reply._replyId = None
                    inbox = self._inboxById.get(reply.toAddr.connectionId, Missing)
                    if inbox:
                        _PPMsg(f'unroutable', msg._msgId)
                        inbox.put_nowait(reply)
        else:
            raise NotYetImplemented('inter-router routing')

    async def _processInboxes(self):
        # We keep a list of tasks waiting for messages to arrive in each connection's inbox. To prevent starvation we
        # schedule them fairly by moving a connection's task that has just been processed to the end of the list thus
        # silent connections bubble to the front. This is mildly wasteful since silent tasks need to be checked each
        # loop but does ensure that busy connections don't dominate.
        tasks = {asyncio.create_task(self._closingDown.wait()): -2}
        running = True
        pending = []
        while running:
            if self._connectionById:
                if self._refreshInboxTasks:
                    # drop any tasks for closed connections
                    tasksToRemove = {t: cid for t, cid in tasks.items() if cid not in self._connectionById and cid > 0}
                    for t in tasksToRemove:
                        # _PPMsg(f'dropping', f'{tasksToRemove[t]}')
                        t.cancel('no longer needed')
                        await asyncio.sleep(0)
                        # t.uncancel()    # "in cases when suppressing asyncio.CancelledError is truly desired, it is necessary to also call uncancel()"
                        tasks.pop(t)
                    await asyncio.gather(*tasksToRemove, return_exceptions=True)
                    # add any new connections
                    for cid, conn in self._connectionById.items():
                        if cid not in tasks.values():
                            tasks[asyncio.create_task(self._inboxById[cid].get())] = cid
                    self._refreshInboxTasks = False
                # wait for one of the tasks to complete
                done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    # pull the done task from the queue
                    connectionId = tasks.pop(task)
                    if connectionId == -2: running = False
                    msg = task.result()
                    if (conn := self._connectionById.get(connectionId, Missing)) is not Missing:
                        inbox = self._inboxById[connectionId]
                        asyncio.create_task(conn._deliver(msg))
                        # add a new task for this connection to the end of the queue
                        tasks[asyncio.create_task(inbox.get())] = connectionId
            else:
                #  sleep briefly and try again
                await asyncio.sleep(0)
        for t in pending:
            t.cancel()
            await asyncio.sleep(0)
        for t in tasks:
            t.cancel()
            await asyncio.sleep(0)
        _PPMsg('shutdown', '')

    # wip

    async def tryStartDirectory(self):
        # try to start the directory here - potentially in a race with other processes
        if self._sDirectoryListener is not Missing: raise ProgrammerError('Already started as a directory')
        if self._sDirectory is not Missing: raise ProgrammerError('Already connected to the local directory')
        sock = pynng.Pair1(polyamorous=True)
        try:
            async with trio.open_nursery() as n:
                sock.add_pre_pipe_connect_cb(self.pre_connect_to_directory)
                sock.add_post_pipe_remove_cb(self.post_remove_from_directory)
                sock.listen(VLM.DIRECTORY_ADDR)
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
                    await trio.sleep(VLM.DIRECTORY_CHECK_INTERVAL / 1000)       # check again later
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
                    sock.dial(VLM.DIRECTORY_ADDR)
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



# **********************************************************************************************************************
# Directory
# **********************************************************************************************************************

class Directory:

    __slots__ = ('_conn', '_entries')

    def __init__(self, router, mode=VLM.LOCAL):
        if router._connectionById.get(VLM.DIRECTORY_CONNECTION_ID, Missing) is not Missing:
            raise RuntimeError('A Directory already exists on this router')
        self._conn = router._newConnection(VLM.DIRECTORY_CONNECTION_ID, self.msgArrived)
        self._entries = []

    async def msgArrived(self, msg):

        if msg.subject == VLM.REGISTER_ENTRY:
            # OPEN: use this instead of a heartbeat
            addr, service, params = msg.contents
            for a, s, p in self._entries:
                if a == addr and s == service and p == params:
                    await self._conn.send( msg.reply(VLM.REGISTER_ENTRY_REPLY, True) )
                    return
            self._entries.append( msg.contents )
            await self._conn.send(msg.reply(VLM.REGISTER_ENTRY_REPLY, True))

        elif msg.subject == VLM.UNREGISTER_ENTRY:
            entry = msg.contents
            self._entries = [e for e in self._entries if e != entry]
            await self._conn.send(msg.reply(VLM.UNREGISTER_ENTRY_REPLY, True))

        elif msg.subject == VLM.UNREGISTER_ADDR:
            addr = msg.contents
            self._entries = [e for e in self._entries if e.addr != addr]
            await self._conn.send(msg.reply(VLM.UNREGISTER_ADDR_REPLY, True))

        elif msg.subject == VLM.GET_ENTRIES:
            if msg.contents:
                await self._conn.send(msg.reply(VLM.GET_ENTRIES_REPLY, [e for e in self._entries if e.service == msg.contents]))
            else:
                await self._conn.send(msg.reply(VLM.GET_ENTRIES_REPLY, self._entries))

        elif msg.subject == VLM.HEARTBEAT:
            # OPEN: should check that a given entry exists
            await self._conn.send(msg.reply(VLM.HEARTBEAT_REPLY, None))

        else:
            await self._conn.send(msg.reply(VLM.DOES_NOT_UNDERSTAND, msg.subject))



# **********************************************************************************************************************
# Utilities
# **********************************************************************************************************************

def _msgAsBytes(msg):
    bytes = io.BytesIO()
    simpleion.dump('1', bytes, binary=True)
    simpleion.dump(msg.fromAddr.routerId, bytes, binary=True)
    simpleion.dump(msg.fromAddr.connectionId, bytes, binary=True)
    if msg.toAddr == VLM.PUB:
        simpleion.dump(None, bytes, binary=True)
        simpleion.dump(None, bytes, binary=True)
    else:
        simpleion.dump(msg.toAddr.routerId, bytes, binary=True)
        simpleion.dump(msg.toAddr.connectionId, bytes, binary=True)
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
        msg = Msg(VLM.PUB, subject, contents)
    msg.fromAddr = Addr(fromAddrSocketAddr, fromAddrConnId)
    msg._msgId = _msgId
    msg._replyId = _replyId
    msg.meta = meta
    # OPEN: assert stream at end
    return msg

def _PPMsg(prefix, msg):
    print(f'{prefix + ":":<15} {msg}')
    return msg
