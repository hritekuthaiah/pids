package expo.modules.pidscamera

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.Log
import android.util.Size
import java.io.ByteArrayOutputStream
import kotlin.math.abs

/**
 * Turns the phone into a camera node: Camera2 preview frames, JPEG-encoded and served
 * as MJPEG on the local network for the edge node to consume.
 *
 * A foreground service of type `camera`, because Android stops background camera
 * access — the guard's screen can be off while the phone watches the room.
 */
class CameraNodeService : Service() {
  private var server: MjpegServer? = null
  private var camera: CameraDevice? = null
  private var session: CameraCaptureSession? = null
  private var reader: ImageReader? = null
  private var thread: HandlerThread? = null
  private var handler: Handler? = null
  private var quality = 70
  private var minIntervalMs = 0L
  private var lastFrameAt = 0L

  override fun onBind(intent: Intent?): IBinder? = null

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    intent ?: return START_NOT_STICKY
    val port = intent.getIntExtra(EXTRA_PORT, 8081)
    val width = intent.getIntExtra(EXTRA_WIDTH, 1280)
    val height = intent.getIntExtra(EXTRA_HEIGHT, 720)
    val fps = intent.getIntExtra(EXTRA_FPS, 15).coerceIn(1, 30)
    quality = intent.getIntExtra(EXTRA_QUALITY, 70).coerceIn(30, 95)
    minIntervalMs = 1000L / fps

    startInForeground(port)
    val worker = HandlerThread("pids-camera").apply { start() }
    thread = worker
    handler = Handler(worker.looper)
    server = MjpegServer(port).also { it.start() }
    openCamera(width, height)
    running = true
    streamUrls = MjpegServer.localAddresses().map { "http://$it:$port/stream.mjpg" }
    return START_REDELIVER_INTENT
  }

  private fun openCamera(width: Int, height: Int) {
    val manager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
    val id = backCameraId(manager) ?: run {
      Log.e(TAG, "no camera available")
      stopSelf()
      return
    }
    val size = bestSize(manager, id, width, height)
    val imageReader = ImageReader.newInstance(size.width, size.height, ImageFormat.YUV_420_888, 2)
    imageReader.setOnImageAvailableListener({ r -> onFrame(r) }, handler)
    reader = imageReader
    try {
      manager.openCamera(
        id,
        object : CameraDevice.StateCallback() {
          override fun onOpened(device: CameraDevice) {
            camera = device
            startSession(device, imageReader)
          }

          override fun onDisconnected(device: CameraDevice) {
            device.close()
            camera = null
          }

          override fun onError(device: CameraDevice, error: Int) {
            Log.e(TAG, "camera error $error")
            device.close()
            camera = null
            stopSelf()
          }
        },
        handler,
      )
    } catch (e: SecurityException) {
      Log.e(TAG, "camera permission missing", e)
      stopSelf()
    }
  }

  private fun startSession(device: CameraDevice, imageReader: ImageReader) {
    val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
      addTarget(imageReader.surface)
      set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
      set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
    }
    @Suppress("DEPRECATION") // SessionConfiguration needs API 28; minSdk here is lower
    device.createCaptureSession(
      listOf(imageReader.surface),
      object : CameraCaptureSession.StateCallback() {
        override fun onConfigured(configured: CameraCaptureSession) {
          session = configured
          configured.setRepeatingRequest(request.build(), null, handler)
        }

        override fun onConfigureFailed(configured: CameraCaptureSession) {
          Log.e(TAG, "capture session failed")
          stopSelf()
        }
      },
      handler,
    )
  }

  /** YUV_420_888 -> NV21 -> JPEG. Pace to the requested rate; drop the rest. */
  private fun onFrame(imageReader: ImageReader) {
    val image = imageReader.acquireLatestImage() ?: return
    try {
      val now = System.currentTimeMillis()
      if (now - lastFrameAt < minIntervalMs) return
      lastFrameAt = now
      val nv21 = toNv21(image)
      val out = ByteArrayOutputStream(nv21.size / 4)
      YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
        .compressToJpeg(Rect(0, 0, image.width, image.height), quality, out)
      server?.publish(out.toByteArray())
    } catch (e: IllegalStateException) {
      Log.w(TAG, "frame dropped", e)
    } finally {
      image.close()
    }
  }

  override fun onDestroy() {
    running = false
    streamUrls = emptyList()
    session?.close()
    session = null
    camera?.close()
    camera = null
    reader?.close()
    reader = null
    server?.stop()
    server = null
    thread?.quitSafely()
    thread = null
    super.onDestroy()
  }

  private fun startInForeground(port: Int) {
    val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    nm.createNotificationChannel(
      NotificationChannel(CHANNEL, "Camera node", NotificationManager.IMPORTANCE_LOW).apply {
        description = "This phone is acting as a PIDS camera"
      }
    )
    val notification = Notification.Builder(this, CHANNEL)
      .setContentTitle("PIDS camera node")
      .setContentText("Streaming to the control room on port $port")
      .setSmallIcon(android.R.drawable.presence_video_online)
      .setOngoing(true)
      .build()
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
    } else {
      startForeground(NOTIFICATION_ID, notification)
    }
  }

  companion object {
    private const val TAG = "PidsCamera"
    private const val CHANNEL = "pids-camera"
    private const val NOTIFICATION_ID = 4243
    const val EXTRA_PORT = "port"
    const val EXTRA_WIDTH = "width"
    const val EXTRA_HEIGHT = "height"
    const val EXTRA_FPS = "fps"
    const val EXTRA_QUALITY = "quality"

    @Volatile var running = false
    @Volatile var streamUrls: List<String> = emptyList()

    private fun backCameraId(manager: CameraManager): String? =
      manager.cameraIdList.firstOrNull {
        manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) ==
          CameraCharacteristics.LENS_FACING_BACK
      } ?: manager.cameraIdList.firstOrNull()

    /** The supported size closest to what was asked for, by total pixels. */
    private fun bestSize(manager: CameraManager, id: String, width: Int, height: Int): Size {
      val map = manager.getCameraCharacteristics(id)
        .get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
      val sizes = map?.getOutputSizes(ImageFormat.YUV_420_888)?.toList().orEmpty()
      val wanted = width.toLong() * height
      return sizes.minByOrNull { abs(it.width.toLong() * it.height - wanted) } ?: Size(width, height)
    }

    /** Row- and pixel-stride aware packing; planes are rarely tightly packed. */
    private fun toNv21(image: android.media.Image): ByteArray {
      val w = image.width
      val h = image.height
      val out = ByteArray(w * h * 3 / 2)
      val y = image.planes[0]
      var pos = 0
      val yBuf = y.buffer
      if (y.rowStride == w) {
        yBuf.get(out, 0, w * h)
        pos = w * h
      } else {
        for (row in 0 until h) {
          yBuf.position(row * y.rowStride)
          yBuf.get(out, pos, w)
          pos += w
        }
      }
      val u = image.planes[1]
      val v = image.planes[2]
      val uBuf = u.buffer
      val vBuf = v.buffer
      for (row in 0 until h / 2) {
        for (col in 0 until w / 2) {
          val index = row * u.rowStride + col * u.pixelStride
          out[pos++] = vBuf.get(index)  // NV21 is VU interleaved
          out[pos++] = uBuf.get(index)
        }
      }
      return out
    }
  }
}
