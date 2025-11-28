# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# goal:
# 1) to establish the identity of the remote peer connected to a pipe
# 2) cancel an incoming connection event that not on the same ipc channel as the one I am already awaiting on (with
#    my queued msgs) to complete - this should help us only have one pipe per remote peer, but needs use to tell the
#    remote dialer to stop dialing as we are on the case
# 2b) or could await a random period and drop any duplicate connections, eventually after a false start or two we
#    should get into a steady state

# need a STOP_DIALING_ME_AND_CLOSE message


# Python imports
import pynng, asyncio, threading, time

# coppertop imports
from coppertop.utils import Missing

# local imports
from vlmessaging._core import _localPipeAddr

MACHINE_MODE = 'MACHINE_MODE'
_DEFAULT_LOCAL_CONNECTION_TIMESOUT = 2000


class _MesagesAwaitingConnection:
    __slots__ = ('msgs', '_expiryTimeMs')
    def __init__(self, timeout, maxQueue=Missing):
        self.msgs = []
        self._expiryTimeMs = monotonicTimeMs() + timeout
    def queueMsg(self, msg):
        self.msgs.append(msg)
    @property
    def hasExpired(self):
        return self._expiryTimeMs < monotonicTimeMs()


class FireSock:

    __slots__ = (
        '_routerId', '_sMachine', '_pipeByRouterId', '_routerIdByPipeId', '_dialerByRouterId',
        '_accumulatedMsgsByRouterId', '_isShuttingDownTask', '_isShuttingDown', '_hasShutdown'
    )


    # PUBLIC API

    def __init__(self, routerId):
        self._routerId = Missing
        self._sMachine = Missing
        self._pipeByRouterId = {}
        self._routerIdByPipeId = {}
        self._dialerByRouterId = {}
        self._accumulatedMsgsByRouterId = {}
        self._isShuttingDown = asyncio.Event()
        self._hasShutdown = asyncio.Event()
        self._isShuttingDownTask = asyncio.create_task(self._isShuttingDown.wait())

        self._listenForRouters(routerId)
        asyncio.create_task(self._mainLoop())


    async def shutdown(self):
        self._isShuttingDown.set()
        await until(timeout=10)  # do this here so the client doesn't have to - annoyingly we can't loop until done
        self._hasShutdown.set()

    @property
    def hasShutdown(self):
        return self._hasShutdown


    # MACHINE CONNECTION MANAGEMENT

    def _listenForRouters(self, routerId):
        self._routerId = routerId
        self._sMachine = pynng.Pair1(polyamorous=True)
        self._sMachine.add_post_pipe_connect_cb(self._onRouterConnect)
        self._sMachine.add_post_pipe_remove_cb(self._onRouterDisconnect)
        self._sMachine.listen(_ipcUrl(routerId))

    def _dialRouter(self, routerId, timeout):
        assert routerId not in self._accumulatedMsgsByRouterId
        accumulatedMsgs = self._accumulatedMsgsByRouterId[routerId] = _MesagesAwaitingConnection(timeout)
        self._dialerByRouterId[routerId] = dial(self._sMachine, _ipcUrl(routerId), block=False)
        print(f'{self._routerId} dialing {routerId}')
        return accumulatedMsgs

    # MACHINE SOCKET CALLBACKS

    def _onRouterConnect(self, pipe):
        connection_type = pipeConnectionType(pipe)
        print(f'_onRouterConnect {self._routerId}: connection {connection_type} on channel {pipe.url}')
        send(pipe, self._routerId.encode(), block=False)

    def _onRouterDisconnect(self, pipe):
        routerId = self._routerIdByPipeId.get(pipe.id, 'unknown')
        print(f'_onRouterDisconnect {self._routerId} disconnected from {routerId} on channel {pipe.url}')
        

    # ROUTING

    def send(self, msg, routerId):
        if (pipe := self._pipeByRouterId.get(routerId, Missing)) is Missing:
            if (accumulatedMsgs := self._accumulatedMsgsByRouterId.get(routerId, Missing)) is Missing:
                accumulatedMsgs = self._dialRouter(routerId, _DEFAULT_LOCAL_CONNECTION_TIMESOUT)
            accumulatedMsgs.queueMsg(msg)
        else:
            print(f'{self._routerId} - sending "{msg}" to {routerId}')
            asend(pipe, msg.encode())


    # MAIN LOOP

    async def _mainLoop(self):
        # monitor the socket and the shutdown event
        detailsByTask = {
            self._isShuttingDownTask: 'shutdown',
            arecv(self._sMachine): 'ipc',
        }
        running = True
        pending = []
        while running:

            done, pending = await until(detailsByTask.keys(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                # pull the done task from the queue
                details = detailsByTask.pop(task)
                if details == 'shutdown':
                    print(f'{self._routerId} - shutting down')
                    running = False
                    break
                elif details == 'ipc':
                    msg = task.result()
                    pipe = msg.pipe
                    if pipe.id not in self._routerIdByPipeId:
                        # first message on this pipe is the routerId of the remote peer
                        routerId = msg.bytes.decode()
                        if routerId in self._pipeByRouterId:
                            print(f'{self._routerId} - WARNING: already connected to {routerId} - overwriting previous connection')
                            self._routerIdByPipeId[pipe.id] = routerId
                            self._pipeByRouterId[routerId] = pipe
                        else:
                            self._routerIdByPipeId[pipe.id] = routerId
                            self._pipeByRouterId[routerId] = pipe
                            print(f'{self._routerId} receiving connection from {routerId}')
                        # send any queued messages
                        if (queuedMsgs := self._accumulatedMsgsByRouterId.pop(routerId, Missing)) is not Missing:
                            for queuedMsg in queuedMsgs.msgs:
                                print(f'{self._routerId} - sending queued "{queuedMsg}" to {routerId}')
                                asend(pipe, queuedMsg.encode())
                    else:
                        ppMsg = f'{self._routerId} received: "{msg.bytes.decode()}" from: {self._routerIdByPipeId[pipe.id]}'
                        _msgLog.append(ppMsg)
                        print(ppMsg)
                    # reissue the ipc task
                    detailsByTask[arecv(self._sMachine)] = details

        for t in pending:
            t.cancel()
            await until(timeout=0)
        for t in detailsByTask.keys():
            t.cancel()
            await until(timeout=0)
        print(f'{self._routerId} - shutdown', '')



_msgLog = []


async def main():

    fred = FireSock('fred')
    joe = FireSock('joe')

    print(1)
    fred.send('hi', 'joe')
    # await asyncio.sleep(0.2)        # comment this out to see connection racing

    print(2)
    joe.send('hello', 'fred')
    print(3)
    fred.send('hi 2', 'joe')
    print(4)
    joe.send('hello 2', 'fred')

    print(4)
    await asyncio.sleep(0.2)

    print(3)
    fred.send('hi 3', 'joe')
    print(4)
    joe.send('hello 3', 'fred')

    print(4)
    await asyncio.sleep(2)

    print(5)
    await fred.shutdown()
    await joe.shutdown()

    await until([fred.hasShutdown, joe.hasShutdown])


    print('done')


def arecv(s):
    return asyncio.create_task(s.arecv_msg())

def dial(s, addr, *, block):
    return s.dial(addr, block=block)

def pipeConnectionType(pipe):
    try:
        pipe.listener
        return 'incoming'
    except TypeError:
        pipe.dialer
        return 'outgoing'

def send(p, bytes, *, block):
    assert not isinstance(bytes, str)
    p.socket.send_msg(pynng.Message(bytes, p), block)

def asend(p, bytes):
    return asyncio.create_task(p.asend(bytes))

def monotonicTimeMs():
    # we can be in control of time for testing etc
    try:
        return asyncio.get_running_loop().time() * 1000
    except RuntimeError:
        return time.monotonic() * 1000

tDictKeys = type({}.keys())
tDictValues = type({}.values())

async def until(*awaitables, return_when=asyncio.ALL_COMPLETED, timeout=None):
    """Wraps any Event in awaitables in a Task then returns await asyncio.wait(...)."""
    things = awaitables
    if len(awaitables) == 1:
        if isinstance(awaitables[0], (list, tuple, set)):
            things = awaitables[0]
        elif isinstance(awaitables[0], (tDictKeys, tDictValues)):
            things = list(awaitables[0])
    things = [eventWaitingTask(thing) if isinstance(thing, asyncio.Event) else thing for thing in things]
    secs = timeout / 1000.0 if timeout else None
    if awaitables:
        return await asyncio.wait(things, timeout=secs, return_when=return_when)
    elif timeout is not None:
        await asyncio.sleep(timeout / 1000.0)     # even if timeout == 0 yield at least once
        return [], []
    else:
        return [], []

def eventWaitingTask(ev):
    async def _(ev):
        return await ev.wait()
    return asyncio.create_task(_(ev))

def _ipcUrl(routerId):
    return f'ipc:///tmp/router_{routerId!s}'


asyncio.run(main())


