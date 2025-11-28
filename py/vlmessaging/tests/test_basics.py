# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# vlmessaging imports
from vlmessaging import Msg, Addr, Router, VLM, utils

# local imports
from vlmessaging._core import _msgFromBytes, _msgAsBytes


def test_serialise():
    msg1 = Msg(Addr(None, 1, 3), 'TEST', dict(hello='world'))
    msg1.fromAddr = Addr(None, 1, 2)
    msg1._msgId = 1
    bytes = _msgAsBytes(msg1)
    msg2 = _msgFromBytes(bytes)
    assert msg1.toAddr == msg2.toAddr
    assert msg1.fromAddr == msg2.fromAddr
    assert msg1.subject == msg2.subject
    assert msg1._msgId == msg2._msgId
    assert msg1._replyId == msg2._replyId
    assert msg1.contents == msg2.contents
    assert msg1.meta == msg2.meta


class AddOneAgent:
    def __init__(self, router):
        self.conn = router.newConnection(self.msgArrived)

    async def msgArrived(self, msg):
        if msg.subject == 'ADD_ONE':
            await self.conn.send(msg.reply(msg.contents + 1))
        else:
            raise NotImplementedError()


def test_local():

    async def run_add_one_test():
        router = Router(mode=VLM.LOCAL_MODE, name='fred')
        fred = AddOneAgent(router)
        conn = router.newConnection()
        reply = await conn.send(Msg(fred.conn.addr, 'ADD_ONE', 41), 1_000)

        assert reply.contents == 42

        router.shutdown()
        await utils.until(router.hasShutdown)

    utils.startEventLoopWith(run_add_one_test)



def test_ipc():

    async def run_add_one_test():
        router1 = Router(mode=VLM.MACHINE_MODE, canRunLocalHubDirectory=False, name='fred')
        router2 = Router(mode=VLM.MACHINE_MODE, canRunLocalHubDirectory=False, name='joe')
        fred = AddOneAgent(router1)
        conn = router2.newConnection()
        reply = await conn.send(Msg(fred.conn.addr, 'ADD_ONE', 41), 1_000)

        assert reply.contents == 42

        router1.shutdown()
        router2.shutdown()
        await utils.until((router1.hasShutdown, router2.hasShutdown))

    utils.startEventLoopWith(run_add_one_test)



def test_tcp():

    async def run_add_one_test():
        router1 = Router(mode=VLM.NETWORK_MODE, canRunLocalHubDirectory=False, name='fred')
        router2 = Router(mode=VLM.NETWORK_MODE, canRunLocalHubDirectory=False, name='joe')
        fred = AddOneAgent(router1)
        conn = router2.newConnection()
        reply = await conn.send(Msg(fred.conn.addr, 'ADD_ONE', 41), 1_000)

        assert reply.contents == 42

        router1.shutdown()
        router2.shutdown()
        await utils.until((router1.hasShutdown, router2.hasShutdown))

    utils.startEventLoopWith(run_add_one_test)


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
    test_local()
    test_ipc()
    # test_tcp()
    print('passed')


if __name__ == '__main__':
    main()
