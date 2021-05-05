import cv2
from amas.agent import Agent, NotWorkingError
from comprex.agent import ABEND, NEND, OBSERVER, RECORDER, START, Stimulator
from comprex.audio import Speaker, Tone
from comprex.scheduler import TrialIterator, uniform_intervals
from comprex.util import timestamp
from pino.config import Experimental
from pino.ino import HIGH, LOW, PinState

INO1_ID = 100
FILMTAKER = "FILMTAKER"


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
                agent.send_to(FILMTAKER, HIGH)
                await agent.call_async(speaker.play, tone)
                agent.send_to(FILMTAKER, LOW)
                if trace_interval > 0:
                    await agent.sleep(trace_interval)
                agent.send_to(RECORDER, timestamp(cs_off))
                agent.send_to(RECORDER, timestamp(us_on))
                await agent.high_for(us, us_duration)
                agent.send_to(RECORDER, timestamp(us_off))
            agent.send_to(OBSERVER, NEND)
            agent.send_to(RECORDER, NEND)
            agent.finish()
    except NotWorkingError:
        agent.send_to(OBSERVER, ABEND)
        agent.send_to(RECORDER, ABEND)
    return None


class FilmTaker(Agent):
    def __init__(self, addr: str):
        super().__init__(addr)
        self._sound = LOW

    @property
    def sound(self) -> PinState:
        return self._sound


async def film(agent: FilmTaker, camid: int, filename: str, rec: bool):
    cap = cv2.VideoCapture(camid)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    cap.set(cv2.CAP_PROP_FPS, 30)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if rec:
        video = cv2.VideoWriter(filename, fourcc, fps, (width, height))

    try:
        while agent.working():
            await agent.sleep(0.025)

            ret, frame = cap.read()
            if not ret:
                continue

            if agent.sound == HIGH:
                cv2.circle(frame, (10, 10), 10, (0, 0, 255), thickness=-1)

            cv2.imshow(f"Camera: {camid}", frame)
            if rec:
                video.write(frame)
            if cv2.waitKey(1) % 0xFF == ord("q"):
                break

        agent.send_to(OBSERVER, NEND)
        agent.send_to(RECORDER, timestamp(NEND))
        agent.finish()
    except NotWorkingError:
        agent.send_to(OBSERVER, ABEND)
        agent.send_to(RECORDER, timestamp(ABEND))
        agent.finish()

    cap.release()
    if rec:
        video.release()
    cv2.destroyAllWindows()
    return None


async def check_pin_state(agent: FilmTaker):
    try:
        while agent.working():
            _, mess = await agent.recv()
            agent._sound = mess
    except NotWorkingError:
        pass
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
    camid = config.experimental.get("cam-id", 0)

    data_dir = join(get_current_file_abspath(__file__), "data")
    if not exists(data_dir):
        mkdir(data_dir)
    filename = join(data_dir, namefile(config.metadata))
    videoname = join(data_dir, namefile(config.metadata, extension="MP4"))

    stimulator = Stimulator(ino=ino) \
        .assign_task(stimulate, expvars=config.experimental) \
        .assign_task(_self_terminate)

    reader = Reader(ino=ino)

    recorder = Recorder(filename=filename)

    rec = config.experimental.get("video-recording")
    filmtaker = FilmTaker(FILMTAKER) \
        .assign_task(film, camid=camid, filename=videoname, rec=rec) \
        .assign_task(check_pin_state) \
        .assign_task(_self_terminate)

    observer = Observer()

    agents = [stimulator, reader, recorder, observer, filmtaker]
    register = Register(agents)
    env_exp = Environment([stimulator, reader, recorder, observer])
    env_cam = Environment([filmtaker])

    try:
        env_cam.parallelize()
        env_exp.run()
        env_cam.join()
    except KeyboardInterrupt:
        observer.send_all(ABEND)
        observer.finish()
