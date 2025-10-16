# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import multiprocessing, time, queue

# 3rd party imports
from coppertop.utils import Missing

# local imports
from vlmessaging import VLM


SHUTDOWN = 'SHUTDOWN'
DOES_NOT_UNDERSTAND = 'DOES_NOT_UNDERSTAND'


class AddSubAgent:

    ADD_ONE = 'ADD_ONE'
    SUB_ONE = 'SUB_ONE'

    def __init__(self):
        self.value = 0  # state

    def addOne(self, x):
        self.value += x
        return self.value

    def subOne(self, x):
        self.value -= x
        return self.value

    def msgArrived(self, msg):
        subject = msg.get('subject')
        if subject == self.ADD_ONE:
            return self.addOne(msg['x'])
        elif subject == self.SUB_ONE:
            return self.subOne(msg['x'])
        else:
            return VLM.DOES_NOT_UNDERSTAND


def test_multiprocess_addOne():
    router = RouterToProcess()
    conn = router.newConnection()

    result = conn.sendAndGet({'to': 1, 'subject': AddSubAgent.ADD_ONE, 'x': 10})
    assert result['result'] == 11, result

    result = conn.sendAndPoll({'to': 1, 'subject': AddSubAgent.SUB_ONE, 'x': 10})
    assert result['result'] == 9, result

    conn.sendAndGet({'to': 0, 'subject': SHUTDOWN})

    # blocking wait until p finishes and closes down
    router.join()


class RouterToProcess:
    def __init__(self):
        self.inBox = multiprocessing.Queue()
        self.outBox = multiprocessing.Queue()
        self.p = multiprocessing.Process(target=route_loop, args=(self.inBox, self.outBox))
        self.process.start()

    def newConnection(self):
        return ConnectionToProcess(self.inBox, self.outBox)

    def join(self):
        self.p.join()


class ConnectionToProcess:
    __slots__ = ('inBox', 'outBox')

    def __init__(self, inBox, outBox):
        self.inBox = inBox
        self.outBox = outBox

    def sendAndGet(self, msg):
        self.inBox.put(msg)
        return self.outBox.get()  # blocking wait

    def sendAndPoll(self, msg):
        self.inBox.put(msg)
        while True:
            try:
                result = self.outBox.get_nowait()
                return result
            except queue.Empty:
                time.sleep(0.1)


def route_loop(inBox, outBox):
    agents = {1: AddSubAgent()}
    while True:
        msg = inBox.get()
        toAddr = msg['to']
        if toAddr == 0:
            if msg['subject'] == SHUTDOWN:
                break
            else:
                outBox.put({'result': DOES_NOT_UNDERSTAND})
                break
        else:
            agent = agents.get(msg['to'], Missing)
            if agent is Missing:
                outBox.put({'result': VLM.MSG_NOT_DELIVERED})
                break



if __name__ == '__main__':
    test_multiprocess_addOne
    print("pass")
