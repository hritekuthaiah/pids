package expo.modules.pidsbadge

import java.nio.ByteBuffer
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * The rolling badge identifier — byte-for-byte the derivation in pids_core.badges:
 * first 8 bytes of HMAC-SHA256(secret, "pids-ble" || uint64_be(window)).
 */
object RollingId {
  private val LABEL = "pids-ble".toByteArray(Charsets.US_ASCII)

  fun window(epochMillis: Long, windowS: Int): Long = Math.floorDiv(epochMillis / 1000L, windowS.toLong())

  fun id(secret: ByteArray, window: Long): ByteArray {
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(secret, "HmacSHA256"))
    mac.update(LABEL)
    mac.update(ByteBuffer.allocate(8).putLong(window).array())
    return mac.doFinal().copyOf(8)
  }

  fun hex(s: String): ByteArray {
    require(s.length % 2 == 0) { "hex string must have an even length" }
    return ByteArray(s.length / 2) { i -> s.substring(2 * i, 2 * i + 2).toInt(16).toByte() }
  }
}
