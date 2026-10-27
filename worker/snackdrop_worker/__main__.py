import asyncio
import logging
import signal

from .agent import Agent, WorkerConfig


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = Agent(WorkerConfig.from_env())

    async def runner() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, agent.stop)
            except NotImplementedError:  # Windows
                pass
        await agent.run_forever()

    asyncio.run(runner())


if __name__ == "__main__":
    main()
