import { NativeModule, requireOptionalNativeModule } from "expo";

declare class PidsBadgeNative extends NativeModule {
  start(secretHex: string, prefixHex: string, companyId: number, windowS: number): void;
  stop(): void;
  isRunning(): boolean;
  currentId(secretHex: string, windowS: number): string;
}

/** Null outside a native Android build (Expo Go, web, tests). */
export default requireOptionalNativeModule<PidsBadgeNative>("PidsBadge");
