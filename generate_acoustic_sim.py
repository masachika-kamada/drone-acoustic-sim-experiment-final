import itertools
import math
import os
import sys

import pyroomacoustics as pra
from tqdm import tqdm

from lib.room import custom_plot
from src.class_room import Room
from src.class_sound import Ambient, AudioLoader, Drone, Voice
from src.file_io import load_config, write_signal_to_npz
from src.snr import adjust_snr

pra.Room.plot = custom_plot


def export_ans(mic_center, sound_positions, output_dir):
    ans = []
    for position in sound_positions:
        dx = position[0] - mic_center[0][0]
        dy = position[1] - mic_center[1][0]
        ans.append(math.atan2(dy, dx))
    ans = sorted(ans)
    with open(f"{output_dir}/ans.txt", "w") as f:
        f.write("\n".join(map(str, ans)))


def main(config, output_dir):
    room = Room(config["pra"])
    AudioLoader.initialize_x_positions_pool(room)
    voice = Voice(config["voice"], config["n_voice"], fs=room.fs, room=room)
    drone = Drone(config["drone"], fs=room.fs)
    if config["n_ambient"] != 0:
        ambient = Ambient(config["ambient"], config["n_ambient"], fs=room.fs, room=room)
    else:
        ambient = None

    room.place_microphones(drone.mic_positions)

    adjust_snr(room, voice, drone, drone.snr, output_dir)
    if ambient is not None:
        adjust_snr(room, voice, ambient, ambient.snr, output_dir)

    room.place_source(voice=voice, drone=drone, ambient=ambient)

    start = int(room.fs * config["processing"]["start_time"])
    end = int(room.fs * config["processing"]["end_time"])

    for signal, name in zip(
        room.simulate(output_dir), ["source", "ncm_rev", "ncm_dir"]
    ):
        signal = signal[:, start:end]
        # signalがint16でオーバーフローするのでnpzで保存する
        write_signal_to_npz(signal, f"{output_dir}/{name}.npz", room.fs)

    sound_positions = voice.positions if ambient is None else voice.positions + ambient.positions
    export_ans(room.rooms["source"].mic_array.center, sound_positions, output_dir)


def update_config(
    config, height, roughness, material, n_voice, n_ambient, snr_ego, snr_ambient
):
    config["drone"]["mic_positions"]["height"] = height
    config["pra"]["room"]["floor"]["roughness"] = roughness
    config["pra"]["room"]["floor"]["material"] = material
    config["n_voice"] = n_voice
    config["n_ambient"] = n_ambient
    config["drone"]["snr"] = snr_ego
    config["ambient"]["snr"] = snr_ambient
    return config


def create_output_directory(*args):
    output_dir = f"experiments/{'-'.join(map(str, args))}/simulation"
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


class TqdmPrintRedirect:
    def __init__(self, tqdm_object):
        self.tqdm_object = tqdm_object
        self.original_write = tqdm_object.fp.write

    def write(self, message):
        # tqdmのオリジナルwriteメソッドを使用
        self.original_write(message)


if __name__ == "__main__":
    config = load_config("experiments/config.yaml")

    # heights = [2, 3, 4, 5]
    # roughnesses = [[0.1, 1.0], [0.5, 2.0], [1.0, 3.0]]
    # materials = ["brickwork", "plasterboard", "rough_concrete", "wooden_lining"]
    # n_voices = [1, 2, 3]
    # n_ambients = [0, 1, 2]
    # snr_egos = [8, 11, 14]
    # snr_ambients = [-3, 0, 3]

    heights = [2, 3]
    roughnesses = [[0.1, 1.0]]
    materials = ["brickwork"]
    n_voices = [2]
    n_ambients = [1]
    snr_egos = [8]
    snr_ambients = [0]

    params_list = list(itertools.product(
        heights,
        roughnesses,
        materials,
        n_voices,
        n_ambients,
        snr_egos,
        snr_ambients,
    ))

    # プログレスバーがアクティブな間、sys.stdoutを上書き
    with tqdm(total=len(params_list)) as pbar:
        original_stdout = sys.stdout
        sys.stdout = TqdmPrintRedirect(pbar)

        for params in params_list:
            updated_config = update_config(config, *params)
            output_dir = create_output_directory(*params)
            main(config, output_dir)
            pbar.update(1)

        # プログレスバー終了後に元のstdoutに戻す
        sys.stdout = original_stdout
