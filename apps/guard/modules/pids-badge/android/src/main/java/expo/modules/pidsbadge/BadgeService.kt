package expo.modules.pidsbadge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.BluetoothManager
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.BluetoothLeAdvertiser
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log

/**
 * Foreground service that keeps advertising the rolling badge id while the guard is on
 * shift — screen off, app in the background. Rotates at every window boundary.
 */
class BadgeService : Service() {
  private val handler = Handler(Looper.getMainLooper())
  private var advertiser: BluetoothLeAdvertiser? = null
  private var secret = ByteArray(0)
  private var prefix = ByteArray(0)
  private var companyId = 0xFFFF
  private var windowS = 30
  private var advertising = false

  private val callback = object : AdvertiseCallback() {
    override fun onStartSuccess(settingsInEffect: AdvertiseSettings) {
      advertising = true
    }

    override fun onStartFailure(errorCode: Int) {
      advertising = false
      Log.w(TAG, "BLE advertise failed: $errorCode")
    }
  }

  private val rotate = object : Runnable {
    override fun run() {
      restart()
      val now = System.currentTimeMillis()
      val next = (RollingId.window(now, windowS) + 1) * windowS * 1000L
      handler.postDelayed(this, next - now + 50)
    }
  }

  override fun onBind(intent: Intent?): IBinder? = null

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    intent ?: return START_NOT_STICKY
    secret = RollingId.hex(intent.getStringExtra(EXTRA_SECRET) ?: return START_NOT_STICKY)
    prefix = RollingId.hex(intent.getStringExtra(EXTRA_PREFIX) ?: return START_NOT_STICKY)
    companyId = intent.getIntExtra(EXTRA_COMPANY, 0xFFFF)
    windowS = intent.getIntExtra(EXTRA_WINDOW, 30)
    startInForeground()
    advertiser = (getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter?.bluetoothLeAdvertiser
    handler.removeCallbacks(rotate)
    handler.post(rotate)
    running = true
    return START_REDELIVER_INTENT
  }

  private fun restart() {
    val adv = advertiser ?: return
    try {
      if (advertising) adv.stopAdvertising(callback)
      val id = RollingId.id(secret, RollingId.window(System.currentTimeMillis(), windowS))
      val settings = AdvertiseSettings.Builder()
        .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
        .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)
        .setConnectable(false)
        .build()
      val data = AdvertiseData.Builder()
        .setIncludeDeviceName(false)
        .setIncludeTxPowerLevel(false)
        .addManufacturerData(companyId, prefix + id)
        .build()
      adv.startAdvertising(settings, data, callback)
    } catch (e: SecurityException) {
      Log.w(TAG, "BLUETOOTH_ADVERTISE permission missing", e)
    }
  }

  private fun startInForeground() {
    val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    nm.createNotificationChannel(
      NotificationChannel(CHANNEL, "Badge", NotificationManager.IMPORTANCE_LOW).apply {
        description = "Your phone is acting as your PIDS badge"
      }
    )
    val notification = Notification.Builder(this, CHANNEL)
      .setContentTitle("PIDS badge active")
      .setContentText("You are identified to the perimeter system")
      .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
      .setOngoing(true)
      .build()
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
    } else {
      startForeground(NOTIFICATION_ID, notification)
    }
  }

  override fun onDestroy() {
    handler.removeCallbacks(rotate)
    try {
      if (advertising) advertiser?.stopAdvertising(callback)
    } catch (_: SecurityException) {
    }
    advertising = false
    running = false
    super.onDestroy()
  }

  companion object {
    private const val TAG = "PidsBadge"
    private const val CHANNEL = "pids-badge"
    private const val NOTIFICATION_ID = 4242
    const val EXTRA_SECRET = "secret"
    const val EXTRA_PREFIX = "prefix"
    const val EXTRA_COMPANY = "company"
    const val EXTRA_WINDOW = "window"

    @Volatile
    var running = false
  }
}
