// Pilot B ground-truth app (native Kotlin). Same five benign behaviours as
// ../testapp_flutter, using platform APIs directly and no third-party libraries.
package com.johnwogu.pilot.nativeapp

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.CancellationSignal
import android.provider.ContactsContract
import android.view.WindowInsets
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.util.concurrent.Executors

private const val POST_URL = "https://httpbin.org/post"
private const val DUMMY_KEY = "PILOT_DUMMY_KEY_123"
private const val FILE_NAME = "pilot_file.txt"
private const val REQ_LOCATION = 1
private const val REQ_CONTACTS = 2

class MainActivity : Activity() {
    private lateinit var output: TextView
    private val executor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            // targetSdk 36 is edge-to-edge: pad by the system-bar insets.
            setOnApplyWindowInsetsListener { v, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars())
                v.setPadding(pad + bars.left, pad + bars.top, pad + bars.right, pad + bars.bottom)
                insets
            }
        }
        root.addView(TextView(this).apply {
            text = "Pilot B — Native"
            textSize = 22f
            setPadding(0, 0, 0, pad)
        })
        output = TextView(this).apply { text = "Tap a button." }
        val buttons = listOf(
            "1. Read location" to ::readLocation,
            "2. Count contacts" to ::readContactsCount,
            "3. POST to httpbin" to ::postJson,
            "4. File write/read" to ::fileRoundTrip,
            "5. Show masked key" to ::showMaskedKey,
        )
        for ((label, action) in buttons) {
            root.addView(Button(this).apply {
                text = label
                setOnClickListener { action() }
            })
        }
        root.addView(output)
        setContentView(root)
    }

    private fun show(label: String, result: String) = runOnUiThread { output.text = "$label → $result" }

    private fun hasPermission(p: String) = checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        when {
            !granted -> show(if (requestCode == REQ_LOCATION) "1. Read location" else "2. Count contacts", "permission denied")
            requestCode == REQ_LOCATION -> readLocation()
            requestCode == REQ_CONTACTS -> readContactsCount()
        }
    }

    // B1: location (runtime permission).
    private fun readLocation() {
        val label = "1. Read location"
        if (!hasPermission(Manifest.permission.ACCESS_FINE_LOCATION)) {
            requestPermissions(
                arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
                REQ_LOCATION,
            )
            return
        }
        val lm = getSystemService(LocationManager::class.java)
        val onLocation = { loc: Location? ->
            show(label, if (loc == null) "no fix" else "%.4f, %.4f".format(loc.latitude, loc.longitude))
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                lm.getCurrentLocation(LocationManager.GPS_PROVIDER, CancellationSignal(), mainExecutor) { onLocation(it) }
            } else {
                @Suppress("DEPRECATION")
                lm.requestSingleUpdate(LocationManager.GPS_PROVIDER, { onLocation(it) }, mainLooper)
            }
        } catch (e: SecurityException) {
            show(label, "error: $e")
        }
    }

    // B2: contacts count only (runtime permission).
    private fun readContactsCount() {
        val label = "2. Count contacts"
        if (!hasPermission(Manifest.permission.READ_CONTACTS)) {
            requestPermissions(arrayOf(Manifest.permission.READ_CONTACTS), REQ_CONTACTS)
            return
        }
        executor.execute {
            val count = contentResolver.query(
                ContactsContract.Contacts.CONTENT_URI,
                arrayOf(ContactsContract.Contacts._ID), null, null, null,
            )?.use { it.count } ?: 0
            show(label, "$count contacts")
        }
    }

    // B3: HTTPS POST of a dummy JSON payload.
    private fun postJson() {
        val label = "3. POST to httpbin"
        executor.execute {
            val result = try {
                val conn = URL(POST_URL).openConnection() as HttpURLConnection
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write("""{"pilot":"hello","n":1}""".toByteArray()) }
                val code = conn.responseCode
                conn.disconnect()
                "HTTP $code"
            } catch (e: Exception) {
                "error: $e"
            }
            show(label, result)
        }
    }

    // B4: write and read a file in app-private storage.
    private fun fileRoundTrip() {
        val file = File(filesDir, FILE_NAME)
        file.writeText("pilot ${Instant.now()}")
        show("4. File write/read", "read back: ${file.readText()}")
    }

    // B5: hardcoded dummy API key, displayed masked.
    private fun showMaskedKey() {
        val key = DUMMY_KEY
        show("5. Show masked key", key.take(4) + "*".repeat(key.length - 7) + key.takeLast(3))
    }
}
