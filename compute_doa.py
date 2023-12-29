import argparse
import os

import numpy as np
from tqdm import tqdm

from lib.custom import create_doa_object, perform_fft_on_frames
from src.class_sound import Drone
from src.file_io import load_config, load_signal_from_npz
from src.metrics import export_metrics
from src.visualization_tools import plot_music_spectra


class DoaProcessor:
    def __init__(self, args, experiment_dir, drone, fs, num_src, frame_length, ans):
        self.args = args
        self.experiment_dir = experiment_dir
        self.drone = drone
        self.fs = fs
        self.num_src = num_src
        self.frame_length = frame_length
        self.ans = ans

    def process_method(self, method, suffix, X_source, X_ncm):
        output_dir = f"{self.experiment_dir}/{method}_{suffix}" if method == "GEVD" else f"{self.experiment_dir}/{method}"
        os.makedirs(output_dir, exist_ok=True)

        doa = create_doa_object(
            method=method,
            source_noise_thresh=100,
            mic_positions=self.drone.mic_positions,
            fs=self.fs,
            nfft=self.args.window_size,
            num_src=self.num_src,
            output_dir=output_dir,
        )

        for f in range(0, X_source.shape[2], self.frame_length // 4):
            xs = X_source[:, :, f : f + self.frame_length]
            if method == "SEVD":
                xn = None
            else:
                xn = X_ncm[:, :, f : f + self.frame_length] if "stable" not in suffix else X_ncm

            if suffix is not None and "diff" in suffix:
                doa.locate_sources(xs, xn, freq_range=self.args.freq_range, auto_identify=True, ncm_diff=0.05)
            else:
                doa.locate_sources(xs, xn, freq_range=self.args.freq_range, auto_identify=True)

        plot_music_spectra(doa, output_dir=output_dir)
        np.save(f"{output_dir}/decomposed_values.npy", np.array(doa.decomposed_values_strage))
        np.save(f"{output_dir}/decomposed_vectors.npy", np.array(doa.decomposed_vectors_strage))
        np.save(f"{output_dir}/spectra.npy", np.array(doa.spectra_storage))
        export_metrics(output_dir, doa.spectra_storage, self.ans)


def main(args, config, experiment_dir):
    config_drone = config["drone"]
    fs = config["pra"]["room"]["fs"]
    drone = Drone(config_drone, fs=fs)

    signal_source, fs = load_signal_from_npz(f"{experiment_dir}/simulation/source.npz")
    signal_ncm_rev, fs = load_signal_from_npz(f"{experiment_dir}/simulation/ncm_rev.npz")
    signal_ncm_dir, fs = load_signal_from_npz(f"{experiment_dir}/simulation/ncm_dir.npz")

    with open(f"{experiment_dir}/simulation/ans.txt") as f:
        ans = [float(line) for line in f.readlines()]

    X_source = perform_fft_on_frames(signal_source, args.window_size, args.hop_size)
    X_ncm_rev = perform_fft_on_frames(signal_ncm_rev, args.window_size, args.hop_size)
    X_ncm_dir = perform_fft_on_frames(signal_ncm_dir, args.window_size, args.hop_size)

    num_voice = int(experiment_dir.split(";")[3])
    num_ambient = int(experiment_dir.split(";")[4])
    num_src = num_voice + num_ambient + 1
    frame_length = 100

    processor = DoaProcessor(args, experiment_dir, drone, fs, num_src, frame_length, ans)

    """ SEVD """
    processor.process_method("SEVD", None, X_source, None)

    """ GEVD """
    # incremental
    frame_s = 140
    frame_t_n = 90
    X_source_i = X_source[:, :, : -(frame_s + frame_t_n)]
    X_ncm_i = X_ncm_dir[:, :, frame_s + frame_t_n :]
    processor.process_method("GEVD", "incremental", X_source_i, X_ncm_i)

    # ans
    processor.process_method("GEVD", "ans_dir", X_source, X_ncm_dir)
    processor.process_method("GEVD", "ans_rev", X_source, X_ncm_rev)

    # diff
    processor.process_method("GEVD", "diff_dir", X_source, X_ncm_dir)
    processor.process_method("GEVD", "diff_rev", X_source, X_ncm_rev)

    # stable
    processor.process_method("GEVD", "stable_dir", X_source, X_ncm_dir)
    processor.process_method("GEVD", "stable_rev", X_source, X_ncm_rev)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate room acoustics based on YAML config.")
    parser.add_argument("--window_size", default=512, type=int, help="Window size for FFT")
    parser.add_argument("--hop_size", default=128, type=int, help="Hop size for FFT")
    parser.add_argument("--freq_range", default=[300, 3500], type=int, nargs=2, help="Frequency range for DoA")
    parser.add_argument("--source_noise_thresh", default=100, type=int, help="Frequency range for DoA")
    args = parser.parse_args()

    config = load_config("experiments/config.yaml")

    base_path = "experiments"
    experiment_dirs = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))])
    for experiment_dir in tqdm(experiment_dirs, desc="Processing experiments"):
        main(args, config, os.path.join(base_path, experiment_dir))
