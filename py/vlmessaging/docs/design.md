
## Which eventloop libraries can be run on other threads? ##

asyncio event loops can be run in any thread, including background threads, using loop.run_forever() or
loop.run_until_complete().

trio does not support running its event loop outside the main thread; it must run in the main thread.

Other libraries:
- curio: Like Trio, expects to run in the main thread.
- Twisted: Can run in any thread, but typically runs in the main thread.
- uvloop (an alternative event loop for asyncio): Can be run in any thread, just like asyncio.

Summary:
- asyncio and uvloop can run in other threads.
- trio and curio require the main thread.



## uvloop vs asyncio ##

uvloop is a drop-in replacement for the default asyncio event loop, but it is implemented in Cython and uses libuv
under the hood. Here are the main differences:
- Performance: uvloop is much faster than the default asyncio event loop, often providing significant speedups.
- Implementation: asyncio's default event loop is written in pure Python (with some C extensions), while uvloop is
  built on top of libuv (the same library used by Node.js).
- API: Both provide the same API, so you can switch to uvloop by just setting it as the event loop policy.
- Compatibility: uvloop is compatible with most asyncio code, but some low-level features or platform-specific
  behaviors may differ.
- Platform support: uvloop is primarily supported on Unix-like systems (Linux, macOS), not Windows.

In summary: uvloop is a high-performance, drop-in replacement for the default asyncio event loop, with the same API
but faster and implemented in Cython using libuv.



## LEARNING ##
- in asyncio a "task" is a stack, a "future" is an object that is awaiting a reply
- asyncio.create_task(...) schedules a coroutine to run in the background and returns a Task object.
- A Task is defined by the asyncio library in Python, not by the Python language itself. It is an object that wraps
  and manages the execution of a coroutine within an event loop. Other async libraries (like Trio) have their own
  task concepts, but Task as a class is from asyncio.

