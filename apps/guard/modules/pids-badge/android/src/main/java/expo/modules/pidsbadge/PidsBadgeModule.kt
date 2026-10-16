package expo.modules.pidsbadge

import android.content.Intent
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/** JS surface: start/stop the badge service and ask whether it is running. */
class PidsBadgeModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("PidsBadge")

    Function("start") { secretHex: String, prefixHex: String, companyId: Int, windowS: Int ->
      val context = appContext.reactContext ?: throw Exceptions.ReactContextLost()
      val intent = Intent(context, BadgeService::class.java)
        .putExtra(BadgeService.EXTRA_SECRET, secretHex)
        .putExtra(BadgeService.EXTRA_PREFIX, prefixHex)
        .putExtra(BadgeService.EXTRA_COMPANY, companyId)
        .putExtra(BadgeService.EXTRA_WINDOW, windowS)
      context.startForegroundService(intent)
    }

    Function("stop") {
      val context = appContext.reactContext ?: throw Exceptions.ReactContextLost()
      context.stopService(Intent(context, BadgeService::class.java))
    }

    Function("isRunning") { BadgeService.running }

    Function("currentId") { secretHex: String, windowS: Int ->
      // Exposed for the parity test between Kotlin and pids_core.badges.
      RollingId.id(RollingId.hex(secretHex), RollingId.window(System.currentTimeMillis(), windowS))
        .joinToString("") { "%02x".format(it) }
    }
  }
}
