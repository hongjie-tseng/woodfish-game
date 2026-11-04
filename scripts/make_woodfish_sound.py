"""合成木魚敲擊聲，輸出 16-bit 單聲道 WAV（只用 Python 標準函式庫）。

木頭與空腔的聲音：開頭一個極短的敲擊雜音，接著低沉的本體共振，
40–80 ms 內就衰減完，而且越高的頻率消失得越快；不像金屬會持續共鳴。

    python scripts/make_woodfish_sound.py app/static/assets/woodfish-hit.wav --size medium
"""
import argparse
import math
import random
import struct
import wave

RATE = 44100

# (本體頻率 Hz, 空腔頻率 Hz)：木魚越大聲音越低
SIZES = {"small": (680, 360), "medium": (480, 260), "large": (330, 180)}


def synthesize(body: float, cavity: float, duration: float = 0.16, seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    # 本體模態不是整數倍頻（木頭的特徵），高的模態衰減更快
    modes = [
        (cavity, 0.45, 0.030),
        (body, 1.00, 0.045),
        (body * 2.37, 0.32, 0.014),
        (body * 4.81, 0.12, 0.006),
    ]
    samples, noise_state, low_state = [], 0.0, 0.0
    phases = [0.0] * len(modes)
    for index in range(int(RATE * duration)):
        t = index / RATE
        glide = 1 + 0.06 * math.exp(-t / 0.012)  # 敲下瞬間木頭被壓緊，音高略高再回落
        value = 0.0
        for number, (frequency, amplitude, decay) in enumerate(modes):
            phases[number] += 2 * math.pi * frequency * glide / RATE
            value += amplitude * math.exp(-t / decay) * math.sin(phases[number])
        # 木槌碰到木頭的「喀」：約 5 ms 的帶通雜音
        white = rng.uniform(-1, 1)
        noise_state += 0.35 * (white - noise_state)  # 去掉最尖的高頻
        low_state += 0.02 * (noise_state - low_state)  # 去掉低頻，留下中高頻的敲擊感
        value += 0.9 * (noise_state - low_state) * math.exp(-t / 0.0015)
        attack = min(1.0, t / 0.0004)  # 0.4 ms 起音，避免數位爆音
        release = min(1.0, (duration - t) / 0.02)  # 結尾 20 ms 淡出
        samples.append(value * attack * release)
    peak = max(abs(value) for value in samples)
    return [value / peak * 0.9 for value in samples]


def write_wav(path: str, samples: list[float]) -> None:
    with wave.open(path, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(b"".join(struct.pack("<h", round(value * 32767)) for value in samples))


def main() -> None:
    parser = argparse.ArgumentParser(description="合成木魚敲擊聲")
    parser.add_argument("output", help="輸出的 WAV 檔路徑")
    parser.add_argument("--size", choices=SIZES, default="medium", help="木魚大小：small 高、large 低")
    args = parser.parse_args()
    write_wav(args.output, synthesize(*SIZES[args.size]))


if __name__ == "__main__":
    main()
