import pynng, asyncio, time



dict_keys = type({}.keys())
dict_values = type({}.values())

def newSock(op):
    if op == 1:
        return pynng.Pair0()
    elif op == 2:
        return pynng.Pair1(opener=pynng.lib.nng_pair1_open)
    elif op == 3:
        return pynng.Pair1(opener=pynng.lib.nng_pair1_open_poly)


def play():
    async def _(op):
        s1 = newSock(op)
        s1Pipes = {}
        def s1Connect(pipe):
            s1Pipes.setdefault(pipe, 0)
            s1Pipes[pipe] += 1
            print(f"s1Connect: {pipeId(pipe)} #{s1Pipes[pipe]}")
        s1.add_post_pipe_connect_cb(s1Connect)
        s1.listen(f'ipc:///tmp/s1_a_{op}')
        s1.listen(f'ipc:///tmp/s1_b_{op}')
        s1.dial(f'ipc:///tmp/s3_a_{op}', block=False)
        s1.dial(f'ipc:///tmp/s3_b_{op}', block=False)


        s2 = newSock(op)
        s2Pipes = {}
        def s2Connect(pipe):
            s2Pipes.setdefault(pipe, 0)
            s2Pipes[pipe] += 1
            print(f"s2Connect: {pipeId(pipe)} #{s2Pipes[pipe]}")
        s2.add_post_pipe_connect_cb(s2Connect)
        s2.listen(f'ipc:///tmp/s2_a_{op}')
        s2.listen(f'ipc:///tmp/s2_b_{op}')
        s2.dial(f'ipc:///tmp/s3_a_{op}', block=False)
        s2.dial(f'ipc:///tmp/s3_b_{op}', block=False)


        s3 = newSock(op)
        s3Pipes = {}
        def s3Connect(pipe):
            s3Pipes.setdefault(pipe, 0)
            s3Pipes[pipe] += 1
            print(f"s3Connect: {pipeId(pipe)} #{s3Pipes[pipe]}")
        s1.add_post_pipe_connect_cb(s1Connect)
        s3.add_post_pipe_connect_cb(s3Connect)
        s3.listen(f'ipc:///tmp/s3_a_{op}')
        s3.listen(f'ipc:///tmp/s3_b_{op}')
        s3.dial(f'ipc:///tmp/s1_a_{op}', block=False)
        s3.dial(f'ipc:///tmp/s1_b_{op}', block=False)
        s3.dial(f'ipc:///tmp/s2_a_{op}', block=False)
        s3.dial(f'ipc:///tmp/s2_b_{op}', block=False)

        await until(timeout=1000)
        for pipe, n in s3Pipes.items():
            print(f'sending from s3 via {pipeId(pipe)}, count: {n}')
            cosend(pipe, f'hello from s3 via {pipeId(pipe)}'.encode())
        await until(timeout=500)

        print(f's1: #{len(s1Pipes)}, s2: #{len(s2Pipes)}, s3: #{len(s3Pipes)}')

        t1 = corecv(s1)
        t2 = corecv(s2)
        N, M = 0, 0
        timer = Timer(100000)
        while M < len(s3Pipes) and not timer:
            done, pending = await until([t1, t2], timeout=500, return_when=asyncio.FIRST_COMPLETED)
            N += 1
            for task in done:
                M += 1
                msg = task.result()
                if msg.pipe in s1Pipes:
                    print(f'{(N, M)} s1 received: "{msg.bytes.decode()}"')
                    t1 = corecv(s1)
                elif msg.pipe in s2Pipes:
                    print(f'{(N, M)} s2 received: "{msg.bytes.decode()}"')
                    t2 = corecv(s2)
                else:
                    raise Exception("impossible")

        t1.cancel()
        t2.cancel()

        for d in s1.dialers:
            d.close()
        for d in s2.dialers:
            d.close()
        for d in s3.dialers:
            d.close()


    asyncio.run(_(1))
    print('--------------------------------------------------------------------------------------------------')
    asyncio.run(_(2))
    print('--------------------------------------------------------------------------------------------------')
    asyncio.run(_(3))
    print('--------------------------------------------------------------------------------------------------')

def corecv(s):
    return asyncio.create_task(s.arecv_msg())

def cosend(p, bytes):
    return asyncio.create_task(p.asend(bytes))

def pipeId(p):
    try:
        url = p.url
    except:
        url = 'no url'
    return f'{id(p)}({url})'

async def until(*awaitables, return_when=asyncio.ALL_COMPLETED, timeout=None):
    """Wraps any Event in awaitables in a Task then returns await asyncio.wait(...)."""
    things = awaitables
    if len(awaitables) == 1:
        if isinstance(awaitables[0], (list, tuple, set)):
            things = awaitables[0]
        elif isinstance(awaitables[0], (dict_keys, dict_values)):
            things = list(awaitables[0])
    things = [taskOnEvent(thing) if isinstance(thing, asyncio.Event) else thing for thing in things]
    secs = timeout / 1000.0 if timeout else None
    if awaitables:
        return await asyncio.wait(things, timeout=secs, return_when=return_when)
    elif timeout is not None:
        await asyncio.sleep(timeout / 1000.0)     # even if timeout == 0 yield at least once
        return [], []
    else:
        return [], []

def taskOnEvent(ev):
    return asyncio.create_task(ev.wait())

class Timer:
    __slots__ = ('_deadline')
    def __init__(self, timeoutInMilliseconds:float):
        self._deadline = time.monotonic() + timeoutInMilliseconds / 1000.0
    def __bool__(self):
        # returns True if timer has expired
        return time.monotonic() >= self._deadline
    def __repr__(self) -> str:
        return f"<timer expired={not not self}>"

play()
