# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# goal:
# 1) to understand nng tcp sockets more thoroughly in particular connection events


# Python imports
import pynng, asyncio, time

# vlmessaging imports
from vlmessaging.utils import Missing

# local imports
from vlmessaging._utils.pp import _PPMsg
from vlmessaging._core import Msg, Addr, _msgAsBytes, _msgFromBytes, _ROUTER_REP, _MsgAccumulator


MACHINE_MODE = 'MACHINE_MODE'
_STOP_DIALING_ME_AND_CLOSE = "STOP_DIALING_ME_AND_CLOSE"
_DEFAULT_LOCAL_CONNECTION_TIMESOUT = 2000


class FireSock:
    __slots__ = (
        '_name', '_ep', '_sock', '_pipeByNEp', '_nEpByPipeId', '_dialerByNEp', '_accumulatedMsgsByNEp',
        '_taskListChanged', '_isShuttingDownTask', '_isShuttingDown', '_hasShutdown'
    )

    # PUBLIC API

    def __init__(self, name, nEp=Missing):
        self._name = name
        self._ep = nEp
        self._sock = Missing
        self._pipeByNEp = {}
        self._nEpByPipeId = {}
        self._dialerByNEp = {}
        self._accumulatedMsgsByNEp = {}

        self._taskListChanged = asyncio.Event()
        self._isShuttingDown = asyncio.Event()
        self._hasShutdown = asyncio.Event()
        self._isShuttingDownTask = asyncio.create_task(self._isShuttingDown.wait())

        self._sock = pynng.Pair1(polyamorous=True)
        self._sock.add_post_pipe_connect_cb(self._onConnect)
        self._sock.add_post_pipe_remove_cb(self._onDisconnect)

        if nEp is not Missing:
            self.nEpListen(nEp)
        asyncio.create_task(self._mainLoop())

    async def shutdown(self):
        self._isShuttingDown.set()
        await until(timeout=10)  # do this here so the client doesn't have to - annoyingly we can't loop until done
        self._hasShutdown.set()

    @property
    def hasShutdown(self):
        return self._hasShutdown


    # MACHINE CONNECTION MANAGEMENT

    def nEpListen(self, nEp):
        self._ep = nEp
        self._sock.listen(nEp)
        self._taskListChanged.set()

    def _dialRouter(self, nEp, timeout):
        assert nEp not in self._accumulatedMsgsByNEp
        accumulatedMsgs = self._accumulatedMsgsByNEp[nEp] = _MsgAccumulator(timeout)
        self._dialerByNEp[nEp] = dial(self._sock, nEp, block=False)
        _PPMsg('DialingRouter', f'{self._name} dialing {nEp}')
        return accumulatedMsgs


    # MACHINE SOCKET CALLBACKS

    def _onConnect(self, pipe):
        if pipe.url.startswith('tcp://'):
            if f'tcp://{pipe.local_address}' == self._ep:
                self._onIncomingTcpConnect(pipe)
            else:
                self._onOutGoingTcpConnect(pipe)
        else:
            _PPMsg('connect', f'{self._name} - NotYetImplemented connection on channel {pipe.url}')

    def _onIncomingTcpConnect(self, pipe):
        localNEpRandomPort = f'tcp://{pipe.local_address}'
        ep = f'tcp://{pipe.remote_address}'
        _PPMsg('connectTcpIn', f'{self._name} - accepted connection from {ep}')

    def _onOutGoingTcpConnect(self, pipe):
        localNEpRandomPort = f'tcp://{pipe.local_address}'
        ep = f'tcp://{pipe.remote_address}'
        _PPMsg('connectTcpOut', f'{self._name} - connected to {ep} from {localNEpRandomPort}')
        self._pipeByNEp[ep] = pipe
        # tell the other end who we are
        msg = Msg(Addr(ep, None, _ROUTER_REP), "SET_ROUTE_FOR_NEP", (self._name, localNEpRandomPort))
        msg.replyAddr = Addr(self._name, None, _ROUTER_REP)
        send(pipe, _msgAsBytes(msg), block=False)

    def _onDisconnect(self, pipe):
        nEp = self._nEpByPipeId.pop(pipe.id, 'unknown')
        _PPMsg('disconnect', f'{self._name} - disconnected from {nEp} on channel {pipe.url}')
        self._pipeByNEp.pop(nEp, None)


    # ROUTING

    def send(self, msg, nEp):
        if (pipe := self._pipeByNEp.get(nEp, Missing)) is Missing:
            if (accumulatedMsgs := self._accumulatedMsgsByNEp.get(nEp, Missing)) is Missing:
                accumulatedMsgs = self._dialRouter(nEp, _DEFAULT_LOCAL_CONNECTION_TIMESOUT)
            accumulatedMsgs.queueMsg(msg)
        else:
            print(f'{self._name} - sending "{msg}" to {nEp}')
            cosend(pipe, msg.encode())


    # MAIN LOOP

    async def _mainLoop(self):
        # monitor the socket and the shutdown event
        taskList = {
            self._isShuttingDownTask: 'shutdown',
            taskOnEvent(self._taskListChanged): 'tasklist',
        }
        running = True
        pending = []
        while running:
            try:
                done, pending = await until(taskList.keys(), return_when=asyncio.FIRST_COMPLETED)
            except Exception as ex:
                raise
            for task in done:
                details = taskList.pop(task)  # take task from list

                if details == 'ipc':
                    nngMsg = task.result()
                    pipe = nngMsg.pipe
                    msg = _msgFromBytes(nngMsg.bytes)
                    if pipe.id not in self._nEpByPipeId:
                        # first message on this pipe is the nEp of the remote peer
                        assert msg.subject == "SET_ROUTE_FOR_NEP"
                        nEp = msg.contents[0]
                        if nEp in self._pipeByNEp:
                            print(f'{self._name} - WARNING: already connected to {nEp} - overwriting previous connection')
                            self._nEpByPipeId[pipe.id] = nEp
                            self._pipeByNEp[nEp] = pipe
                        else:
                            self._nEpByPipeId[pipe.id] = nEp
                            self._pipeByNEp[nEp] = pipe
                            print(f'{self._name} receiving connection from {nEp}')
                        # send any queued messages
                        if (queuedMsgs := self._accumulatedMsgsByNEp.pop(nEp, Missing)) is not Missing:
                            for queuedMsg in queuedMsgs.msgs:
                                print(f'{self._name} - sending queued "{queuedMsg}" to {nEp}')
                                cosend(pipe, queuedMsg.encode())
                    else:
                        ppMsg = f'{self._name} received: "{msg.bytes.decode()}" from: {self._nEpByPipeId[pipe.id]}'
                        _msgLog.append(ppMsg)
                        print(ppMsg)
                    taskList[corecv(self._sock)] = details  # add task to bottom of list

                elif details == 'tasklist':
                    if self._sock and 'ipc' not in taskList.values():
                        taskList[corecv(self._sock)] = 'ipc'
                        _PPMsg(f'TaskList', f'adding ipc on {self._name}')
                    self._taskListChanged.clear()
                    taskList[task] = details

                elif details == 'shutdown':
                    _PPMsg(f'ShuttingDown', f'{self._name}')
                    running = False
                    break

                else:
                    raise ValueError(f'Unknown monitor type "{details.type}".')

        for t in pending:
            t.cancel()
            await until(timeout=0)
        for t in taskList.keys():
            t.cancel()
            await until(timeout=0)
        _PPMsg(f'ShutDown', f'{self._name}')


_msgLog = []


async def main():
    fred = FireSock('fred', 'tcp://127.0.0.1:30001')
    joe = FireSock('joe')

    print(1)
    joe.send('hello', 'tcp://127.0.0.1:30001')

    print(2)
    await asyncio.sleep(2)

    print(3)
    await fred.shutdown()
    await joe.shutdown()

    await until([fred.hasShutdown, joe.hasShutdown])

    print('done')


def corecv(s):
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


def cosend(p, bytes):
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
    things = [taskOnEvent(thing) if isinstance(thing, asyncio.Event) else thing for thing in things]
    secs = timeout / 1000.0 if timeout else None
    if awaitables:
        return await asyncio.wait(things, timeout=secs, return_when=return_when)
    elif timeout is not None:
        await asyncio.sleep(timeout / 1000.0)  # even if timeout == 0 yield at least once
        return [], []
    else:
        return [], []


def taskOnEvent(ev):
    return asyncio.create_task(ev.wait())



asyncio.run(main())


