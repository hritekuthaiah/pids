package expo.modules.pidscamera

import android.util.Log
import java.io.IOException
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread

/**
 * The smallest HTTP server that can feed an MJPEG stream to the edge node: one
 * `multipart/x-mixed-replace` response per viewer, each fed the latest frame.
 *
 * Deliberately plain HTTP on the local network and nothing else — no file system, no
 * commands, one path. The frames leave the phone only while the guard has the camera
 * screen open, and nothing is written to storage (NFR-04).
 */
class MjpegServer(private val port: Int) {
  private val boundary = "pidsframe"
  private var server: ServerSocket? = null
  private val viewers = CopyOnWriteArrayList<Viewer>()
  @Volatile private var running = false
  @Volatile private var latest: ByteArray? = null

  val viewerCount: Int
    get() = viewers.size

  fun start() {
    if (running) return
    running = true
    val socket = ServerSocket(port)
    socket.reuseAddress = true
    server = socket
    thread(name = "pids-mjpeg-accept", isDaemon = true) {
      while (running) {
        try {
          accept(socket.accept())
        } catch (e: IOException) {
          if (running) Log.w(TAG, "accept failed", e)
        }
      }
    }
  }

  fun stop() {
    running = false
    for (v in viewers) v.close()
    viewers.clear()
    try {
      server?.close()
    } catch (_: IOException) {
    }
    server = null
  }

  /** Hand the newest JPEG to every viewer; slow viewers simply miss frames. */
  fun publish(jpeg: ByteArray) {
    latest = jpeg
    for (v in viewers) {
      if (!v.offer(jpeg)) {
        viewers.remove(v)
        v.close()
      }
    }
  }

  private fun accept(socket: Socket) {
    val viewer = Viewer(socket, boundary)
    val request = viewer.readRequestLine()
    when {
      request == null -> viewer.close()
      request.contains("/snapshot.jpg") -> {
        viewer.sendSnapshot(latest)
        viewer.close()
      }
      request.contains("/healthz") -> {
        viewer.sendText("ok\n")
        viewer.close()
      }
      else -> {
        viewer.beginStream()
        latest?.let { viewer.offer(it) }
        viewers.add(viewer)
      }
    }
  }

  private class Viewer(private val socket: Socket, private val boundary: String) {
    private val out = socket.getOutputStream()

    fun readRequestLine(): String? =
      try {
        socket.soTimeout = 3000
        val line = socket.getInputStream().bufferedReader().readLine()
        socket.soTimeout = 0
        line
      } catch (_: IOException) {
        null
      }

    fun beginStream() {
      write(
        "HTTP/1.0 200 OK\r\n" +
          "Content-Type: multipart/x-mixed-replace; boundary=$boundary\r\n" +
          "Cache-Control: no-store\r\n\r\n"
      )
    }

    fun sendSnapshot(jpeg: ByteArray?) {
      if (jpeg == null) {
        write("HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
        return
      }
      write("HTTP/1.0 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: ${jpeg.size}\r\n\r\n")
      out.write(jpeg)
      out.flush()
    }

    fun sendText(body: String) =
      write("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\nContent-Length: ${body.length}\r\n\r\n$body")

    fun offer(jpeg: ByteArray): Boolean =
      try {
        write("--$boundary\r\nContent-Type: image/jpeg\r\nContent-Length: ${jpeg.size}\r\n\r\n")
        out.write(jpeg)
        out.write("\r\n".toByteArray())
        out.flush()
        true
      } catch (_: IOException) {
        false
      }

    fun close() {
      try {
        socket.close()
      } catch (_: IOException) {
      }
    }

    private fun write(s: String) {
      out.write(s.toByteArray())
      out.flush()
    }
  }

  companion object {
    private const val TAG = "PidsCamera"

    /** Every LAN address this phone can be reached on, so the operator can read one off. */
    fun localAddresses(): List<String> =
      NetworkInterface.getNetworkInterfaces()
        .toList()
        .filter { it.isUp && !it.isLoopback }
        .flatMap { it.inetAddresses.toList() }
        .filter { !it.isLoopbackAddress && it.isSiteLocalAddress && it is InetAddress }
        .map { it.hostAddress ?: "" }
        .filter { it.isNotEmpty() && !it.contains(':') }
  }
}
