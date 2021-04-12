from typing import Any, Callable, List, Optional, Tuple

from amas.agent import Agent, NotWorkingError
from comprex.agent import ABEND, NEND, OBSERVER, RECORDER, START
from comprex.audio import Speaker, Tone
from comprex.scheduler import (TrialIterator, elementwise_shuffle,
                               uniform_intervals)
from comprex.util import timestamp
from pino.config import Experimental
from pino.ino import HIGH, LOW, Arduino, Optuino

INOSTIMUMALTOR = "inostimulator"
OPTSTIMUMALTOR = "optstimulator"

INO1_ID = 100
INO2_ID = 200


class ExperimentalStimulator(Agent):
    def __init__(self):
        super().__init__(INOSTIMUMALTOR)


async def exp_stimulate(agent: ExperimentalStimulator, ino: Arduino,
                        expvars: Experimental) -> None:
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
                agent.send_to(OPTSTIMUMALTOR, interval)
                print(f"Trial: {trial}")
                await agent.sleep(interval)
                agent.send_to(RECORDER, timestamp(cs_on))
                await agent.call_async(speaker.play, tone)
                await agent.sleep(trace_interval)
                agent.send_to(RECORDER, timestamp(cs_off))
                agent.send_to(RECORDER, timestamp(us_on))
                ino.digital_write(us, HIGH)
                await agent.sleep(us_duration)
                ino.digital_write(us, LOW)
                agent.send_to(RECORDER, timestamp(us_off))
            agent.send_to(OBSERVER, NEND)
            agent.finish()
    except NotWorkingError:
        agent.send_to(OBSERVER, ABEND)
    return None


# OptStimulatorはInoStimulatorからISIを受信
# ISI +/- s秒経過後に1秒間`pulse_on` (但し s < ISI)
class OptStimulator(Agent):
    def __init__(self):
        super().__init__(OPTSTIMUMALTOR)


def identity(x: Any) -> Any:
    def inner() -> float:
        return x

    return inner


def range_of(x: List[float], size: int) -> Callable:
    intervals = uniform_intervals(x[0], x[1], size)
    i = 0

    def inner() -> float:
        nonlocal i
        interval = intervals[i]
        i += 1
        return interval

    return inner


PulseSettingIndex = int
StimTimingGenerator = Callable
Condition = Optional[Tuple[PulseSettingIndex, StimTimingGenerator]]
TrialIndex = int


def generate_trial_conditions(
        optvars: Experimental,
        expvars: Experimental) -> Tuple[List[Condition], List[TrialIndex]]:
    freqs = optvars.get("frequencies", [5, 10, 20])
    pulse_idx = list(range(len(freqs)))
    # 3: number of condition of stimulation timing (no-cs, cs, us)
    number_of_condition = len(pulse_idx) * 3
    trial = expvars.get("trial", 120)
    no_stim_idx = number_of_condition
    ist = optvars.get("inter-stimulation-trial", 2)
    trial_idx = [
        [cond_idx] + [no_stim_idx] * ist  # Add no-stim trials after stim trial
        for cond_idx in range(number_of_condition)
    ]
    # adjust number of stim trial to occupy `stim_prop`% of whole trial.
    stim_prop = optvars.get("propotion-of-stimulate", 0.2)
    number_each_condition = int(stim_prop * trial // len(trial_idx))
    trial_idx *= number_each_condition
    # Fill the rest of the trials with no stim trials.
    trial_idx.extend([[no_stim_idx]
                      for _ in range(trial - len(trial_idx * (ist + 1)))])
    trial_idx = elementwise_shuffle(trial_idx)
    trial_idx = sum(trial_idx, [])  # flattening nested list

    us_timer = identity(optvars.get("us", 0))
    cs_timer = identity(optvars.get("cs", -1))
    # 3: number of stim timing condition
    no_cs_timer = range_of(optvars.get("no-cs", [-4, 2]),
                           number_each_condition * 3)
    conditions: List[Condition] = [(idx, t) for idx in pulse_idx
                                   for t in [us_timer, cs_timer, no_cs_timer]]
    conditions.append(None)  # Add no-stim condition
    return (conditions, trial_idx)


async def opt_stimulate(agent: OptStimulator, ino: Optuino,
                        expvars: Experimental, optvars: Experimental) -> None:
    freqs = optvars.get("frequencies", [10, 20])
    duration = optvars.get("diuration", 30)
    pulse_idxs = list(range(len(freqs)))
    pulse_pin = optvars.get("pin", 12)
    # sec into millisec
    stim_duration = optvars.get("stimulate-duration", 1000) / 1000

    [ino.set_pulse_params(i, freqs[i], duration) for i in pulse_idxs]
    ino.digital_write(pulse_pin, LOW)

    conditions, trial_idx = generate_trial_conditions(optvars, expvars)

    trials = TrialIterator(list(range(len(conditions))), conditions)
    trials.set_sequence(trial_idx)

    try:
        while agent.working():
            for _, cond in trials:
                _, isi = await agent.recv(1)
                if cond is None:
                    continue
                pulse_idx, pulse_timer = cond
                await agent.sleep(isi - pulse_timer())
                freq = ino.pulse_frequency[pulse_idx]
                ino.pulse_on(pulse_pin, pulse_idx)
                agent.send_to(RECORDER, timestamp(INO2_ID + freq))
                await agent.sleep(stim_duration)
                ino.pulse_off()
                agent.send_to(RECORDER, timestamp(-(INO2_ID + freq)))
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
    from pino.ino import Comport
    from pino.ui.clap import PinoCli

    configs = PinoCli().get_configs()
    # `--yamls` `path/to/experimental.yaml` `path/to/opt.yaml`
    experimntal_condig = configs[0]
    opt_config = configs[1]

    expcom = Comport() \
        .apply_settings(experimntal_condig.comport) \
        .set_timeout(1.0) \
        .deploy() \
        .connect()

    optcom = Comport() \
        .apply_settings(opt_config.comport) \
        .set_timeout(1.0) \
        .deploy() \
        .connect()

    expino = Arduino(expcom)
    expino.apply_pinmode_settings(experimntal_condig.pinmode)

    optino = Optuino(optcom)
    optino.apply_pinmode_settings(opt_config.pinmode)

    data_dir = join(get_current_file_abspath(__file__), "data")
    if not exists(data_dir):
        mkdir(data_dir)
    filename = join(data_dir, namefile(experimntal_condig.metadata))

    exp_stimulator = ExperimentalStimulator() \
        .assign_task(exp_stimulate, ino=expino,
                     expvars=experimntal_condig.experimental) \
        .assign_task(_self_terminate)
    opt_stimulator = OptStimulator() \
        .assign_task(opt_stimulate, ino=optino,
                     optvars=opt_config.experimental,
                     expvars=experimntal_condig.experimental) \
        .assign_task(_self_terminate)
    reader = Reader(ino=expino)
    recorder = Recorder(filename=filename)
    observer = Observer()
    agents = [exp_stimulator, opt_stimulator, reader, recorder, observer]
    register = Register(agents)
    env = Environment(agents)

    try:
        env.run()
    except KeyboardInterrupt:
        observer.send_all(ABEND)
        observer.finish()
