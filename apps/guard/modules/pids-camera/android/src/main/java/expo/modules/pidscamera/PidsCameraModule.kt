package expo.modules.pidscamera

import android.content.Intent
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/** JS surface: start/stop the camera node and report the URLs it can be reached on. */
class PidsCameraModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("PidsCamera")

    Function("start") { port: Int, width: Int, height: Int, fps: Int, quality: Int ->
      val context = appContext.reactContext ?: throw Exceptions.ReactContextLost()
      val intent = Intent(context, CameraNodeService::class.java)
        .putExtra(CameraNodeService.EXTRA_PORT, port)
        .putExtra(CameraNodeService.EXTRA_WIDTH, width)
        .putExtra(CameraNodeService.EXTRA_HEIGHT, height)
        .putExtra(CameraNodeService.EXTRA_FPS, fps)
        .putExtra(CameraNodeService.EXTRA_QUALITY, quality)
      context.startForegroundService(intent)
    }

    Function("stop") {
      val context = appContext.reactContext ?: throw Exceptions.ReactContextLost()
      context.stopService(Intent(context, CameraNodeService::class.java))
    }

    Function("isRunning") { CameraNodeService.running }

    Function("streamUrls") { CameraNodeService.streamUrls }

    Function("localAddresses") { MjpegServer.localAddresses() }
  }
}
