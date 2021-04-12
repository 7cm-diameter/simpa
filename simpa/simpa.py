from amas.agent import NotWorkingError
from comprex.agent import ABEND, NEND, OBSERVER, RECORDER, START, Stimulator
from comprex.audio import Speaker, Tone
from comprex.scheduler import TrialIterator, uniform_intervals
from comprex.util import timestamp
from pino.config import Experimental

INO1_ID = 100


async def stimulate(agent: Stimulator, expvars: Experimental) -> None:
    speaker = Speaker(expvars.get("speaker", 0))
    cs_duration = expvars.get("cs-duration", 1.0)
    freq = expvars.get("frequency", 6000)
    tone = Tone(freq, cs_duration)

    cs = int(freq)
    us = expvars.get("us", 12)
    us_duration = expvars.get("us-duration", 0.05)

    # event ids
    cs_on = cs
    cs_off = -cs
    us_on = us + INO1_ID
    us_off = -(us + INO1_ID)

    trial = expvars.get("trial", 120)
    trace_interval = expvars.get("trace-interval", 1.)
    mean_iti = expvars.get("mean-iti", 20.0) - (cs_duration + trace_interval)
    range_iti = expvars.get("range-iti", 5.0)
    intervals = uniform_intervals(mean_iti, range_iti, trial)

    trials = TrialIterator(list(range(trial)), intervals)

    try:
        agent.send_to(RECORDER, timestamp(START))
        while agent.working():
            for trial, interval in trials:
                print(f"Trial: {trial}")
                await agent.sleep(interval)
                agent.send_to(RECORDER, timestamp(cs_on))
                await agent.call_async(speaker.play, tone)
                await agent.sleep(trace_interval)
                agent.send_to(RECORDER, timestamp(cs_off))
                agent.send_to(RECORDER, timestamp(us_on))
                await agent.high_for(us, us_duration)
                agent.send_to(RECORDER, timestamp(us_off))
            agent.send_to(OBSERVER, NEND)
            agent.finish()
    except NotWorkingError:
        agent.send_to(OBSERVER, ABEND)
    return None


if __name__ == '__main__':
    from os import mkdir
    from os.path import exists, join

    from amas.connection import Register
    from amas.env import Environment
    from comprex.agent import Observer, Reader, Recorder, _self_terminate
    from comprex.util import get_current_file_abspath, namefile
    from pino.ino import Arduino, Comport
    from pino.ui.clap import PinoCli

    config = PinoCli().get_config()

    com = Comport() \
        .apply_settings(config.comport) \
        .set_timeout(1.0) \
        .deploy() \
        .connect()

    ino = Arduino(com)
    ino.apply_pinmode_settings(config.pinmode)

    data_dir = join(get_current_file_abspath(__file__), "data")
    if not exists(data_dir):
        mkdir(data_dir)
    filename = join(data_dir, namefile(config.metadata))

    stimulator = Stimulator(ino=ino) \
        .assign_task(stimulate, expvars=config.experimental) \
        .assign_task(_self_terminate)
    reader = Reader(ino=ino)
    recorder = Recorder(filename=filename)
    observer = Observer()
    agents = [stimulator, reader, recorder, observer]
    register = Register(agents)
    env = Environment(agents)

    try:
        env.run()
    except KeyboardInterrupt:
        observer.send_all(ABEND)
        observer.finish()
