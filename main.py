import numpy as np
import soundfile as sf
import pyloudnorm as pyln
import sounddevice as sd
import tkinter.filedialog
import tkinter as tk
from pathlib import Path


"""
so what does this need to do:
we need t know hw far into the "songs" we are
We can know this by being like: each time we've hit play and
    - changed song
    - paused and restarted
That's how far into the song we are now
    - end_time - start_time = duration played
if we know the duration played then that's great:
    - seeking changes duration played to wherever we click
    - stopping changes duration played to 0

make an update duration_played func
    - takes in time,
    - duration = curr_time - start_time

We need to be able to go from duration played to depth of track.
This is simple though, just multiply the duration played by the sample rate.
start = duration * sample_rate
from_pause = data[:, start:]
"""


class File:
    def __init__(self, path):
        self.path = path
        data, rate = sf.read(path, dtype="float32")
        self.data, self.norm_data = data, data
        self.sample_rate = rate
        self.lufs = self.get_lufs()
        self.string = self.get_string()
        self.length_secs = len(self.data) / self.sample_rate

    def get_lufs(self):
        meter = pyln.Meter(self.sample_rate)
        return meter.integrated_loudness(self.data)

    def normalize_data(self, new_loudness):
        self.norm_data = pyln.normalize.loudness(self.data, self.lufs, new_loudness)

    def play(self, start_time=0, device=None):
        to_play = self.norm_data[int(start_time * self.sample_rate) :, :]
        to_play = self.fade_in(to_play)
        sd.play(to_play, self.sample_rate, device=device)

    def fade_in(self, data):
        fade_len = 20
        fade = np.expand_dims(np.linspace(0, 1, fade_len), axis=1)
        data[:fade_len, :] *= fade
        return data

    def stop_play(self, position=0, device=None):
        sd.stop()

    def get_string(self):
        name = Path(self.path).stem
        lufs = "{:.1f}".format(self.lufs)
        return f"{lufs}   {name}"


class Player:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Music Player")
        self.root.geometry("920x600+290+85")
        self.root.configure(background="#212121")
        tk.Button(self.root, text="load files", command=self.load_files).pack()

        self.table_strings_var = tk.StringVar(value=[])
        lbox = tk.Listbox(self.root, listvariable=self.table_strings_var)
        lbox.pack(fill="both")
        lbox.bind("<<ListboxSelect>>", lambda e: self.track_select(lbox.curselection()))

        self.waveform = tk.Canvas(self.root)
        self.waveform.pack(fill="both")
        self.waveform.bind("<Button-1>", lambda event: self.seek(event.x))

        tk.Button(self.root, text="play", command=self.play).pack()
        tk.Button(self.root, text="pause", command=self.pause).pack()
        tk.Button(self.root, text="stop", command=self.stop).pack()
        self.current_track = -1
        self.duration = Duration()

        self.files = []

        self.update_play()

    def run(self):
        self.root.mainloop()

    def load_files(self):
        file_paths = tkinter.filedialog.askopenfilenames()
        for file_path in file_paths:
            try:
                self.files.append(File(file_path))
            except sf.LibsndfileError:
                pass
        self.update_table()

    def stream_closed(self):
        try:
            sd.get_stream()
            return False
        except RuntimeError:
            return True
        except sd.PortAudioError:
            return True

    def play(self):
        if not self.files:
            return
        if self.current_track == -1:
            print(self.current_track)
            self.track_select((0,))
        else:
            self.files[self.current_track].play(start_time=self.duration.duration)
            self.duration.start(sd.get_stream().time)

    def pause(self):
        if self.stream_closed():
            return
        self.duration.update(sd.get_stream().time)
        self.files[self.current_track].stop_play()

    def stop(self):
        if self.stream_closed():
            return
        self.duration.reset()
        self.files[self.current_track].stop_play()
        self.draw_waveform()

    def update_table(self):
        names = [file.string for file in self.files]
        self.table_strings_var.set(names)

    def track_select(self, selection):
        if not selection:
            return
        self.current_track = selection[0]
        self.get_waveform()
        self.draw_waveform()
        self.play()

    def get_waveform(self):
        width = self.waveform.winfo_width()
        height = self.waveform.winfo_height()
        data = self.files[self.current_track].data
        maxes = np.amax(data, axis=1)
        self.bars = []
        for clump in np.array_split(maxes, width):
            self.bars.append(clump.max() * height)

    def draw_waveform(self):
        self.waveform.delete("all")
        height = self.waveform.winfo_height()
        ratio_played = (
            self.duration.duration / self.files[self.current_track].length_secs
        )
        cutoff = int(len(self.bars) * ratio_played)
        for i, bar in enumerate(self.bars):
            color = "grey" if i < cutoff else "black"
            self.waveform.create_line(i, height, i, height - bar, fill=color, width=1)

    def seek(self, loc):
        width = self.waveform.winfo_width()
        time = self.files[self.current_track].length_secs * (loc / width)
        self.duration.reset(time)
        self.play()

    def update_play(self):
        update_ms = 100
        if self.stream_closed():
            self.root.after(update_ms, self.update_play)
        else:
            self.duration.update(sd.get_stream().time)
            self.draw_waveform()
            self.root.after(update_ms, self.update_play)


class Duration:
    def __init__(self):
        self.last_call = 0
        self.duration = 0

    def update(self, current_time):
        self.duration += current_time - self.last_call
        self.last_call = current_time

    def reset(self, time=0):
        self.duration = time

    def start(self, starting_time):
        self.last_call = starting_time


if __name__ == "__main__":
    test = Player()
    test.run()
