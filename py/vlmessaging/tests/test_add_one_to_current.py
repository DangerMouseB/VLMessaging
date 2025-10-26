# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import asyncio, multiprocessing, os

# 3rd party imports
from coppertop.utils import Missing

# local imports
from vlmessaging import Msg, Router, Entry, Directory, VLM
from vlmessaging.utils import _findSingleEntryAddrOfTypeOrExit, _PPMsg, with_async_init


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



def test_add_one_to_current():

    async def run_add_one_test():
        router = Router()
        directory = Directory(router, VLM.LOCAL)
        a1 = await AddOneToCurrentAgent(router)
        a2 = await GetCurrentAgent(router, 500)
        try:
            await _test_add_one_to_current(router)
            passed = True
        except AssertionError as ex:
            passed = False
        await router.hasShutdown()
        return passed

    res = asyncio.run(run_add_one_test())
    assert res


def _run_all(seqOfFnAndArgs):
    async def _startAgents():
        router = Router()
        agents = []
        passed = True
        for fn, args in seqOfFnAndArgs:
            try:
                agent = await fn(router, *args)
                agents.append(agent)
            except AssertionError as ex:
                passed = False
        await router.shutdown()
        return passed
    res = asyncio.run(_startAgents())
    assert res


def run_in_subprocess():
    p = multiprocessing.Process(target=test_add_one_to_current)

    # p = multiprocessing.Process(target=_run_all, args=(
    #     (Directory, (VLM.LOCAL,)),
    #     (AddOneToCurrentAgent, ()),
    #     (GetCurrentAgent, (500,)),
    #     (_test_add_one_to_current, ()),
    # ))

    p.start()
    p.join()
    print(f'parentid: {os.getpid()}, childid: {p.pid}')



    # p1 = multiprocessing.Process(target=runAll, args=(
    #     (Directory, (VLM.MACHINE,)),
    #     (AddOneToCurrentAgent, ()),
    # ))
    # p2 = multiprocessing.Process(target=runAll, args=(
    #     (Directory, (VLM.MACHINE,)),
    #     (GetCurrentAgent, ()),
    # ))
    # p3 = multiprocessing.Process(target=runAll, args=(
    #     (Directory, (VLM.MACHINE,)),
    #     (AddOneToCurrentAgent, ()),
    # ))




if __name__ == "__main__":
    run_in_subprocess()
    print('passed')
