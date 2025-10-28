# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import asyncio, multiprocessing, os, inspect, itertools
from copy import copy

# 3rd party imports
from coppertop.utils import Missing

# local imports
from vlmessaging import Msg, Router, Entry, Directory, VLM
from vlmessaging.utils import with_async_init
from vlmessaging._utils import _findSingleEntryAddrOfTypeOrExit, _PPMsg


@with_async_init
class GetCurrentAgent:

    __slots__ = ('conn', 'wait', 'running')

    ENTRY_TYPE = 'GetCurrentAgent'
    GET_CURRENT = 'GET_CURRENT'
    KILL = 'KILL'

    async def __init__(self, router, wait):
        self.conn = router.newConnection(self.msgArrived)
        self.wait = wait
        entryAdded = False
        self.running = True
        while not entryAdded:
            msg = Msg(VLM.DIRECTORY, VLM.REGISTER_ENTRY, Entry(self.conn.addr, self.ENTRY_TYPE, None))
            entryAdded = await self.conn.send(msg, 1000)
            if entryAdded: entryAdded = entryAdded.contents

    async def msgArrived(self, msg):
        if not self.running: return

        if msg.subject == self.GET_CURRENT:
            await asyncio.sleep(self.wait / 1000)
            self.wait = max(0, self.wait - 100)
            await self.conn.send( msg.reply(41) )

        if msg.subject == self.KILL:
            self.running = False
            await self.conn.send( msg.reply(None) )
            self.conn = None

        else:
            return [VLM.IGNORE_UNHANDLED_REPLIES, VLM.HANDLE_DOES_NOT_UNDERSTAND]


@with_async_init
class AddOneToCurrentAgent:

    __slots__ = ('conn', 'addrOfGetCurrentAgent')

    ENTRY_TYPE = 'AddOneToCurrentAgent'
    ADD_ONE_TO_CURRENT = 'ADD_ONE_TO_CURRENT'

    async def __init__(self, router):
        self.conn = router.newConnection(self.msgArrived)
        self.addrOfGetCurrentAgent = Missing
        entryAdded = False
        while not entryAdded:
            msg = Msg(VLM.DIRECTORY, VLM.REGISTER_ENTRY, Entry(self.conn.addr, self.ENTRY_TYPE, None))
            entryAdded = await self.conn.send(msg, 1000)
            if entryAdded: entryAdded = entryAdded.contents


    async def msgArrived(self, msg):

        if msg.subject == self.ADD_ONE_TO_CURRENT:
            errMsg = msg.reply(RuntimeError(f'Can\'t find a {GetCurrentAgent.ENTRY_TYPE}'))
            current = Missing
            while not current:
                if self.addrOfGetCurrentAgent is Missing:
                    self.addrOfGetCurrentAgent = await _findSingleEntryAddrOfTypeOrExit(self.conn, GetCurrentAgent.ENTRY_TYPE, 1000, errMsg)
                current = await self.conn.send(Msg(self.addrOfGetCurrentAgent, GetCurrentAgent.GET_CURRENT, Missing), 200)
            reply = msg.reply(current.contents + 1)
            await self.conn.send(reply)

        elif msg.subject == VLM.MSG_NOT_DELIVERED:
            if msg.contents == self.addrOfGetCurrentAgent:
                await self.conn.send(Msg(VLM.DIRECTORY, VLM.UNREGISTER_ADDR, self.addrOfGetCurrentAgent))
                self.addrOfGetCurrentAgent = Missing   # force a rediscovery next time

        else:
            return [VLM.IGNORE_UNHANDLED_REPLIES, VLM.HANDLE_DOES_NOT_UNDERSTAND]



async def _test_add_one_to_current(router):
    conn = router.newConnection()

    # check that AddOneToCurrentAgent can find GetCurrentAgent and get a reply eventually
    addOneAgentAddr = Missing
    while not addOneAgentAddr:
        addOneAgentAddr = await _findSingleEntryAddrOfTypeOrExit(conn, AddOneToCurrentAgent.ENTRY_TYPE, 1000, errMsg=Missing)
    msg = Msg(addOneAgentAddr, AddOneToCurrentAgent.ADD_ONE_TO_CURRENT, None)
    res = await conn.send(msg, 5000)
    _PPMsg(f'Got', f'{res.subject} = {res.contents}')

    # kill off the GetCurrentAgent to test that the AddOneToCurrentAgent copes
    getCurrentAgentAddr = Missing
    while not getCurrentAgentAddr:
        getCurrentAgentAddr = await _findSingleEntryAddrOfTypeOrExit(conn, GetCurrentAgent.ENTRY_TYPE, 1000, errMsg=Missing)
    res = await conn.send(Msg(getCurrentAgentAddr, GetCurrentAgent.KILL, None), 500)
    assert res and res.isReply
    await asyncio.sleep(0.01)
    res = await conn.send(Msg(getCurrentAgentAddr, GetCurrentAgent.KILL, None), 100, additional_subjects=[VLM.MSG_NOT_DELIVERED])
    assert res and res.isReply and res.subject == VLM.MSG_NOT_DELIVERED

    # start a new GetCurrentAgent
    getCurrentAgent = await GetCurrentAgent(router, 0)

    # test resilience of AddOneToCurrentAgent
    msg = Msg(addOneAgentAddr, AddOneToCurrentAgent.ADD_ONE_TO_CURRENT, None)
    res = await conn.send(msg, 5000)
    _PPMsg(f'Got', f'{res.subject} = {res.contents}')
    assert res.contents == 42

    # shutdown the test harness
    await router.shutdown()



def _startAgents(outBox, seqOfFnAndArgs):
    async def _():
        router = Router()
        agents = []
        try:
            for fn, args in seqOfFnAndArgs:
                agent = fn(router, *args)
                if inspect.iscoroutine(agent):
                    agent = await agent
                agents.append(agent)
        except AssertionError as e:
            outBox.put((os.getpid(), False))
            raise e
        finally:
            await router.shutdown()
        await router.hasShutdown()
        outBox.put((os.getpid(), True))
    asyncio.run(_())


def test_add_one_to_current_1():
    outBox = multiprocessing.Queue()
    p = multiprocessing.Process(target=_startAgents, args=(
        outBox,
        [
            (Directory, (VLM.LOCAL,)),
            (AddOneToCurrentAgent, ()),
            (GetCurrentAgent, (500,)),
            (_test_add_one_to_current, ()),
        ]
    ))
    p.start()
    p.join()
    res = outBox.get()
    assert res[1], 'test_add_one_to_current_1 failed'


def test_add_one_to_current_2():
    outBox = multiprocessing.Queue()
    p1 = multiprocessing.Process(target=_startAgents, args=(
        outBox,
        [
            (Directory, (VLM.MACHINE,)),
            (AddOneToCurrentAgent, ()),
        ]
    ))
    p2 = multiprocessing.Process(target=_startAgents, args=(
        outBox,
        [
            (Directory, (VLM.MACHINE,)),
            (GetCurrentAgent, (500,)),
        ]
    ))
    p3 = multiprocessing.Process(target=_startAgents, args=(
        outBox,
        [
            (Directory, (VLM.MACHINE,)),
            (_test_add_one_to_current, ()),
        ]
    ))
    p1.start()
    p2.start()
    p3.start()
    p1.join()
    p2.join()
    p3.join()
    nameByPid = {p1.pid: 'p1', p2.pid: 'p2', p3.pid: 'p3'}
    failures = []
    for _ in range(3):
        res = outBox.get()
        if not res[1]:
            failures.append(nameByPid[res[0]])
    assert not failures, f'test_add_one_to_current_2 failed for {", ".join(failures)}'


class CountFailures(object):
    def __init__(self, counter):
        self.counter = counter
    def __enter__(self):
        return None
    def __exit__(self, type, value, traceback):
        if value is not None: next(self.counter)
        return True


if __name__ == "__main__":
    failures = itertools.count()
    with CountFailures(failures): test_add_one_to_current_1()
    # with CountFailures(failures): test_add_one_to_current_2()
    print()
    print('failed' if failures.__reduce__()[1][0] else 'passed')
