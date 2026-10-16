/**
 * Audible breach alarm: an alternating two-tone (880/660 Hz) — the pattern people
 * already associate with an alarm — generated with WebAudio, so no media files and
 * no network. Browsers only allow audio after a user gesture; the console's first
 * click (logging in) satisfies that.
 */
export class Alarm {
  private ctx: AudioContext | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private high = true;

  private beep(): void {
    const ctx = (this.ctx ??= new AudioContext());
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "square";
    osc.frequency.value = this.high ? 880 : 660;
    this.high = !this.high;
    const t = ctx.currentTime;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.08, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.38);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + 0.4);
  }

  start(): void {
    if (this.timer) return;
    this.beep();
    this.timer = setInterval(() => {
      this.beep();
    }, 450);
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}

export const alarm = new Alarm();
