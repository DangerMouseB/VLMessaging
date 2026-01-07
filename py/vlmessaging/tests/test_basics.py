# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# vlmessaging imports
from vlmessaging import Msg, Addr, Router, VLM, Directory, Entry
from vlmessaging.utils import co, wip, Missing
from vlmessaging._utils.utils import Timer
from vlmessaging._utils.errors import NotYetImplemented

# local imports
from vlmessaging._core import _msgFromBytes, _msgAsBytes


def test_serialise():
    msg1 = Msg(Addr(None, 1, 3), 'TEST', dict(hello='world'))
    msg1.replyAddr = Addr(None, 1, 2)
    msg1._msgId = 1
    bytes = _msgAsBytes(msg1)
    msg2 = _msgFromBytes(bytes)
    assert msg1.toAddr == msg2.toAddr
    assert msg1.replyAddr == msg2.replyAddr
    assert msg1.subject == msg2.subject
    assert msg1._msgId == msg2._msgId
    assert msg1._replyId == msg2._replyId
    assert msg1.contents == msg2.contents
    assert msg1.meta == msg2.meta


class AddOneAgent:
    ENTRY_TYPE = 'AddOneAgent'
    ADD_ONE = 'ADD_ONE'

    def __init__(self, router):
        self.conn = router.newConnection(self.msgArrived)

    async def start(self, vnet=[]):
        msg = Msg(
            self.conn.directoryAddr,
            VLM.REGISTER_ENTRY,
            Entry(
                self.conn.addr,
                AddOneAgent.ENTRY_TYPE,
                params=None,
                vnets=[vnet] if not isinstance(vnet, (list, tuple)) else None,
                perms=None
            )
        )
        reply = await self.conn.send(msg, 500)
        if reply is Missing:
            print('No directory')
        return self


    async def msgArrived(self, msg):
        if msg.subject == AddOneAgent.ADD_ONE:
            await self.conn.send(msg.reply(msg.contents + 1))
        else:
            return [VLM.IGNORE_UNHANDLED_REPLIES, VLM.HANDLE_PING, VLM.HANDLE_DOES_NOT_UNDERSTAND]


def test_router_local():

    async def _():
        router = Router(mode=VLM.LOCAL_MODE, name='fred')
        agent = await AddOneAgent(router).start()
        conn = router.newConnection()
        reply = await conn.send(Msg(agent.conn.addr, AddOneAgent.ADD_ONE, 41), 1_000)

        assert reply.contents == 42

        router.shutdown()
        await co.until(router.hasShutdown)

    co.startEventLoopWith(_)



def test_router_ipc():

    async def _():
        router1 = Router(mode=VLM.MACHINE_MODE, name='fred')
        router2 = Router(mode=VLM.MACHINE_MODE, name='joe')
        agent = await AddOneAgent(router1).start()
        conn = router2.newConnection()
        reply = await conn.send(Msg(agent.conn.addr, AddOneAgent.ADD_ONE, 41), 1000_000)

        assert reply.contents == 42

        router1.shutdown()
        router2.shutdown()
        await co.until((router1.hasShutdown, router2.hasShutdown))

    co.startEventLoopWith(_)



def test_router_tcp():

    async def _():
        router1 = Router(mode=VLM.NETWORK_MODE, name='fred')
        nEp = router1.nEpListen('tcp://127.0.0.1:{N}', 30000, 30010)
        agent = await AddOneAgent(router1).start()

        router2 = Router(mode=VLM.NETWORK_MODE, name='joe')

        conn = router2.newConnection()
        agentAddr = Addr(nEp, agent.conn.addr.mEp, agent.conn.addr.rEp)
        reply = await conn.send(Msg(agentAddr, AddOneAgent.ADD_ONE, 41), 1000)

        assert reply.contents == 42

        router1.shutdown()
        router2.shutdown()
        await co.until((router1.hasShutdown, router2.hasShutdown))

    co.startEventLoopWith(_)



def test_reduce_connections_to_one():

    async def msgArrived(msg):
        print(msg)

    async def _():
        router1 = Router(mode=VLM.MACHINE_MODE, name='fred')
        router2 = Router(mode=VLM.MACHINE_MODE, name='joe')
        conn1 = router1.newConnection(fn=msgArrived)
        conn2 = router2.newConnection(fn=msgArrived)
        await conn1.send(Msg(conn2.addr, 'from fred'))
        await conn2.send(Msg(conn1.addr, 'from joe'))

        await co.until(timeout=100)

        router1.shutdown()
        router2.shutdown()
        await co.until((router1.hasShutdown, router2.hasShutdown))

    co.startEventLoopWith(_)



def test_directory_local():

    async def _():
        r1 = Router(mode=VLM.LOCAL_MODE, name='fred')
        d1 = Directory(r1)

        agent = await AddOneAgent(r1).start()

        conn = r1.newConnection()
        agentAddr = await wip._findSingleEntryAddrOfTypeOrMissing(conn, AddOneAgent.ENTRY_TYPE, 200, errMsg=Missing)
        assert agentAddr
        reply = await conn.send(Msg(agentAddr, 'ADD_ONE', 41), 1_000)
        assert reply.contents == 42

        r1.shutdown()
        await co.until(r1.hasShutdown)

    co.startEventLoopWith(_)



def test_directory_ipc():
    async def _():
        r1 = Router(mode=VLM.MACHINE_MODE, name='fred')
        d1 = Directory(r1,
            hubListen='ipc:///tmp/hub_1',
            heartbeatEntriesTimeout=0,
        )

        r2 = Router(mode=VLM.MACHINE_MODE, name='joe')
        d2 = Directory(r2,
            hubs=['ipc:///tmp/hub_1'],
            heartbeatEntriesTimeout=0,
        )

        agent = await AddOneAgent(r1).start(VLM.LOCAL_VNET)

        conn = r2.newConnection()
        # loop until timeout or the relevant entry appears in d2 (propagated from d1)
        agentAddr = await wip._waitForSingleEntryAddrOfTypeOrReplyAndExit(conn, AddOneAgent.ENTRY_TYPE, 2_000, 200, errMsg=Missing)
        reply = await conn.send(Msg(agentAddr, 'ADD_ONE', 41), 2_000)
        assert reply.contents == 42

        r1.shutdown()
        r2.shutdown()
        await co.until([r1.hasShutdown, r2.hasShutdown])

    co.startEventLoopWith(_)



def test_directory_tcp():
    async def _():
        r1 = Router(mode=VLM.MACHINE_MODE, name='fred')
        d1 = Directory(r1,
            vnets=['test'],
            netListen='tcp://127.0.0.1:30001',
            heartbeatEntriesTimeout=0,
        )

        r2 = Router(mode=VLM.MACHINE_MODE, name='joe')
        d2 = Directory(r2,
            vnets=['test'],
            netHubs=['tcp://127.0.0.1:30001'],
            heartbeatEntriesTimeout=0,
        )

        agent = await AddOneAgent(r1).start('test')

        conn = r2.newConnection()
        # loop until timeout or the relevant entry appears in d2 (propagated from d1)
        agentAddr = await wip._waitForSingleEntryAddrOfTypeOrReplyAndExit(conn, AddOneAgent.ENTRY_TYPE, 2_000, 200, errMsg=Missing)
        reply = await conn.send(Msg(agentAddr, 'ADD_ONE', 41), 1_000)
        assert reply.contents == 42

        r1.shutdown()
        r2.shutdown()
        await co.until([r1.hasShutdown, r2.hasShutdown])

    co.startEventLoopWith(_)


def test_directory_tcp_with_beacon_and_gateway():
    async def _():
        r1 = Router(mode=VLM.MACHINE_MODE, name='fred')
        d1 = Directory(r1,
            vnets=['test'],
            netListen='tcp://127.0.0.1:30001',
            beaconAnnounce='udp://224.1.1.1:30003',
        )

        r2 = Router(mode=VLM.MACHINE_MODE, name='joe')
        d2 = Directory(r2,
            vnets=['test'],
            hubs=['ipc:///tmp/hub_sally'],
            gatewayListen=['ipc:///tmp/gateway_joe'],
            netListen='tcp://127.0.0.1:30002',
            beaconListen=['udp://224.1.1.1:30003'],
        )

        r3 = Router(mode=VLM.MACHINE_MODE, name='sally')
        d3 = Directory(r3,
            vnets=['test'],
            hubListen=['ipc:///tmp/hub_sally'],
            gateways=['ipc:///tmp/gateway_joe'],
        )

        agent = await AddOneAgent(r1).start()

        conn = r3.newConnection()
        # loop until timeout or the relevant entry appears in d3 (propagated from d1)
        agentAddr = await wip._waitForSingleEntryAddrOfTypeOrReplyAndExit(conn, AddOneAgent.ENTRY_TYPE, 5_000, 200, errMsg=Missing)
        reply = await conn.send(Msg(agentAddr, 'ADD_ONE', 41), 1_000)
        assert reply.contents == 42

        r1.shutdown()
        r2.shutdown()
        r3.shutdown()
        await co.until([r1.hasShutdown, r2.hasShutdown, r3.hasShutdown])


    co.startEventLoopWith(_)


# NEXT
# add timers
#   - e.g. keep retrying message every 100ms for up to a 2s connection timeout
#   - initial 2s heatbeat, with exponential backoff up to 16s or whatever
#   - single event timer

# test trying to send one plus messages to a non-existent IPC and TCP address results in MSG_NOT_DELIVERED when
# awaiting connection timeout elapses

# test that sending to a non-existent connection returns MSG_NOT_DELIVERED
# test that unawaited sending to a connection with no handler returns MSG_NOT_DELIVERED
# test that awaited sending to a connection with no handler gets handled as a reply
# test that dropped connections are cleaned up properly
# test VLM.IGNORE_UNHANDLED_REPLIES
# test VLM.HANDLE_DOES_NOT_UNDERSTAND

# msg = Msg(toAddr, "FRED", None)
# res = await conn.send(msg, 5000)

# check shutdown works properly in debug in PyCharm - used to have an asyncio.sleep(0.1) in Router.shutdown that may have helped?


def main():
    test_serialise()
    test_router_local()
    test_router_ipc()
    test_router_tcp()
    test_reduce_connections_to_one()
    test_directory_local()
    test_directory_ipc()
    # test_directory_tcp()
    # test_directory_tcp_with_beacon_and_gateway()
    print('passed')


if __name__ == '__main__':
    main()
