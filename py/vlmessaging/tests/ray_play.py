import ray

try:
    ray.init(address="auto")
except ValueError:
    # start in local mode
    ray.init()

N = 5


@ray.remote
class Worker:
    def __init__(self):
        self.counter = 0

    def doit(self, x):
        self.counter += 1
        return x + 1, self.counter

workers = [Worker.options(name=f"worker-{i}").remote() for i in range(N)]
print("Cluster bootstrap complete.")


proxies = [ray.get_actor(f"worker-{i}") for i in range(N)]
futures = [proxies[i % N].doit.remote(i+100) for i in range(20)]
results = ray.get(futures)
print(results)

