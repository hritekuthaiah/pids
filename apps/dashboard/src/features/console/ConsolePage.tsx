import { AlertQueue } from "../alerts/AlertQueue";
import { CriticalBanner } from "../alerts/CriticalBanner";
import { DetailPanel } from "../alerts/DetailPanel";
import { MapView } from "../map/MapView";
import type { SiteGeo } from "../../lib/hooks";
import { BaselinePanel } from "./BaselinePanel";
import { CameraPanel } from "./CameraPanel";

export function ConsolePage({ site }: { site: SiteGeo }) {
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_400px] gap-2">
      <div className="flex min-h-0 min-w-0 flex-col gap-2">
        <div className="hud relative min-h-0 flex-1 overflow-hidden">
          <MapView site={site} />
          <CriticalBanner />
        </div>
        <div className="flex shrink-0 gap-2">
          <CameraPanel />
          <BaselinePanel />
        </div>
      </div>
      <aside className="flex min-h-0 flex-col gap-2">
        <AlertQueue />
        <DetailPanel />
      </aside>
    </div>
  );
}
