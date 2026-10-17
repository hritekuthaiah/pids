import { NativeModule, requireOptionalNativeModule } from "expo";

declare class PidsCameraNative extends NativeModule {
  start(port: number, width: number, height: number, fps: number, quality: number): void;
  stop(): void;
  isRunning(): boolean;
  /** Every LAN URL this phone is reachable on while streaming. */
  streamUrls(): string[];
  localAddresses(): string[];
}

/** Null outside a native Android build (Expo Go, web, tests). */
export default requireOptionalNativeModule<PidsCameraNative>("PidsCamera");
