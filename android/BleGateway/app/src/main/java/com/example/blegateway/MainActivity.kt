package com.example.blegateway

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.example.blegateway.ui.theme.BleGatewayTheme
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors


data class TagInfo(
    val name: String,
    val address: String,
    val rssi: Int,
    val lastSeen: Long = System.currentTimeMillis()
)


class MainActivity : ComponentActivity() {

    private var bluetoothAdapter: BluetoothAdapter? = null

    private var status by mutableStateOf("Ready")
    private var isScanning by mutableStateOf(false)

    private var scannerZone by mutableStateOf("ZONE-A")

    private var serverUrl by mutableStateOf(
        "http://172.20.3.167:8000/api/v1/scan-data"
    )

    private var serverStatus by mutableStateOf("Not connected")

    private var foundTags by mutableStateOf(
        listOf<TagInfo>()
    )

    private val tagMap =
        mutableMapOf<String, TagInfo>()

    private val uploadHandler =
        Handler(Looper.getMainLooper())

    private val networkExecutor =
        Executors.newSingleThreadExecutor()

    private var startAfterPermission = false


    // ==================================================
    // 1초마다:
    // 1. 오래된 태그 제거
    // 2. 현재 태그 목록 서버로 전송
    // ==================================================

    private val uploadRunnable =
        object : Runnable {

            override fun run() {

                if (!isScanning) {
                    return
                }


                // --------------------------------------
                // 3초 동안 새 BLE 광고가 없으면
                // 현재 감지 목록에서 제거
                // --------------------------------------

                val now =
                    System.currentTimeMillis()

                tagMap.entries.removeIf { entry ->

                    now -
                            entry.value.lastSeen >
                            3000
                }


                foundTags =
                    tagMap.values
                        .toList()
                        .sortedByDescending {
                            it.rssi
                        }


                // --------------------------------------
                // 현재 살아있는 태그 목록 Snapshot
                // --------------------------------------

                val tagsSnapshot =
                    foundTags.toList()


                val zoneSnapshot =
                    scannerZone
                        .trim()
                        .ifBlank {
                            "UNKNOWN_ZONE"
                        }


                val urlSnapshot =
                    serverUrl.trim()


                // --------------------------------------
                // HTTP는 별도 Thread에서 실행
                // --------------------------------------

                networkExecutor.execute {

                    postScanData(
                        urlSnapshot,
                        zoneSnapshot,
                        tagsSnapshot
                    )
                }


                // 1초 뒤 다시 실행
                uploadHandler.postDelayed(
                    this,
                    1000
                )
            }
        }


    // ==================================================
    // Runtime Permission
    // ==================================================

    private val permissionLauncher =
        registerForActivityResult(
            ActivityResultContracts
                .RequestMultiplePermissions()
        ) { permissions ->

            if (
                permissions.values.all { it }
            ) {

                updateBluetoothStatus()

                if (startAfterPermission) {

                    startBleScan()
                }

            } else {

                status =
                    "Permission Denied"
            }

            startAfterPermission = false
        }


    // ==================================================
    // BLE Scan Callback
    // ==================================================

    private val scanCallback =
        object : ScanCallback() {

            @SuppressLint("MissingPermission")
            override fun onScanResult(
                callbackType: Int,
                result: ScanResult
            ) {

                val deviceName =
                    result.scanRecord
                        ?.deviceName
                        ?: result.device.name
                        ?: "Unknown"


                // --------------------------------------
                // TEIA 이름이 포함된 BLE만 사용
                // --------------------------------------

                if (
                    deviceName.contains(
                        "TEIA",
                        ignoreCase = true
                    )
                ) {

                    val address =
                        result.device.address

                    val rssi =
                        result.rssi


                    // 광고가 들어올 때마다
                    // lastSeen이 현재시간으로 새로 생성됨
                    val tag =
                        TagInfo(
                            name = deviceName,
                            address = address,
                            rssi = rssi,
                            lastSeen =
                                System.currentTimeMillis()
                        )


                    runOnUiThread {

                        // 같은 MAC이면 최신 값으로 덮어쓰기
                        tagMap[address] =
                            tag


                        foundTags =
                            tagMap.values
                                .toList()
                                .sortedByDescending {
                                    it.rssi
                                }
                    }
                }
            }


            override fun onScanFailed(
                errorCode: Int
            ) {

                isScanning = false

                stopUploadLoop()

                status =
                    "Scan Failed: Error $errorCode"
            }
        }


    // ==================================================
    // Activity
    // ==================================================

    override fun onCreate(
        savedInstanceState: Bundle?
    ) {

        super.onCreate(
            savedInstanceState
        )


        val bluetoothManager =
            getSystemService(
                Context.BLUETOOTH_SERVICE
            ) as BluetoothManager


        bluetoothAdapter =
            bluetoothManager.adapter


        setContent {

            BleGatewayTheme {

                Scaffold(
                    modifier =
                        Modifier.fillMaxSize()
                ) { innerPadding ->


                    Column(
                        modifier =
                            Modifier
                                .padding(
                                    innerPadding
                                )
                                .padding(
                                    20.dp
                                )
                    ) {


                        Text(
                            "TEIA SmartTag Gateway",
                            style =
                                MaterialTheme
                                    .typography
                                    .headlineSmall
                        )


                        Spacer(
                            modifier =
                                Modifier.height(
                                    12.dp
                                )
                        )


                        OutlinedTextField(
                            value =
                                scannerZone,
                            onValueChange = {

                                scannerZone =
                                    it

                            },
                            label = {

                                Text(
                                    "Gateway Zone ID"
                                )

                            },
                            modifier =
                                Modifier
                                    .fillMaxWidth()
                        )


                        Spacer(
                            modifier =
                                Modifier.height(
                                    10.dp
                                )
                        )


                        OutlinedTextField(
                            value =
                                serverUrl,
                            onValueChange = {

                                serverUrl =
                                    it

                            },
                            label = {

                                Text(
                                    "Server API URL"
                                )

                            },
                            modifier =
                                Modifier
                                    .fillMaxWidth(),
                            singleLine = true
                        )


                        Spacer(
                            modifier =
                                Modifier.height(
                                    12.dp
                                )
                        )


                        Text(
                            "Bluetooth: $status"
                        )


                        Text(
                            "Server: $serverStatus"
                        )


                        Spacer(
                            modifier =
                                Modifier.height(
                                    12.dp
                                )
                        )


                        Button(
                            onClick = {

                                if (
                                    isScanning
                                ) {

                                    stopBleScan()

                                } else {

                                    if (
                                        hasRequiredPermissions()
                                    ) {

                                        startBleScan()

                                    } else {

                                        startAfterPermission =
                                            true

                                        permissionLauncher
                                            .launch(
                                                requiredPermissions()
                                            )
                                    }
                                }
                            },
                            modifier =
                                Modifier
                                    .fillMaxWidth()
                        ) {


                            Text(
                                if (
                                    isScanning
                                ) {

                                    "STOP GATEWAY"

                                } else {

                                    "START GATEWAY"
                                }
                            )
                        }


                        Spacer(
                            modifier =
                                Modifier.height(
                                    20.dp
                                )
                        )


                        Text(
                            "Detected TEIA Tags: ${foundTags.size}",
                            style =
                                MaterialTheme
                                    .typography
                                    .titleMedium
                        )


                        Spacer(
                            modifier =
                                Modifier.height(
                                    10.dp
                                )
                        )


                        LazyColumn {

                            items(
                                foundTags
                            ) { tag ->


                                Card(
                                    modifier =
                                        Modifier
                                            .fillMaxWidth()
                                            .padding(
                                                vertical =
                                                    4.dp
                                            )
                                ) {


                                    Column(
                                        modifier =
                                            Modifier
                                                .padding(
                                                    12.dp
                                                )
                                    ) {


                                        Text(
                                            "Tag ID: ${tag.name}",
                                            style =
                                                MaterialTheme
                                                    .typography
                                                    .titleMedium
                                        )


                                        Text(
                                            "MAC Address: ${tag.address}",
                                            style =
                                                MaterialTheme
                                                    .typography
                                                    .bodySmall
                                        )


                                        Text(
                                            "RSSI (Signal): ${tag.rssi} dBm",
                                            style =
                                                MaterialTheme
                                                    .typography
                                                    .bodyLarge
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }


        checkAndRequestPermissions()
    }


    override fun onResume() {

        super.onResume()

        if (
            !isScanning &&
            hasRequiredPermissions()
        ) {

            updateBluetoothStatus()
        }
    }


    override fun onDestroy() {

        stopUploadLoop()

        if (isScanning) {

            stopBleScan()
        }

        networkExecutor.shutdownNow()

        super.onDestroy()
    }


    // ==================================================
    // Permissions
    // ==================================================

    private fun checkAndRequestPermissions() {

        if (
            hasRequiredPermissions()
        ) {

            updateBluetoothStatus()

        } else {

            permissionLauncher.launch(
                requiredPermissions()
            )
        }
    }


    private fun requiredPermissions():
            Array<String> {

        return if (
            Build.VERSION.SDK_INT >=
            Build.VERSION_CODES.S
        ) {

            arrayOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT
            )

        } else {

            arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION
            )
        }
    }


    private fun hasRequiredPermissions():
            Boolean {

        return requiredPermissions()
            .all {

                ContextCompat
                    .checkSelfPermission(
                        this,
                        it
                    ) ==
                        PackageManager
                            .PERMISSION_GRANTED
            }
    }


    // ==================================================
    // Bluetooth Status
    // ==================================================

    @SuppressLint("MissingPermission")
    private fun updateBluetoothStatus() {

        val adapter =
            bluetoothAdapter


        status =
            when {

                adapter == null ->

                    "Bluetooth Not Supported"


                !adapter.isEnabled ->

                    "Bluetooth OFF"


                else ->

                    "Ready ($scannerZone)"
            }
    }


    // ==================================================
    // Start BLE Scan
    // ==================================================

    @SuppressLint("MissingPermission")
    private fun startBleScan() {

        val adapter =
            bluetoothAdapter


        if (
            adapter == null ||
            !adapter.isEnabled
        ) {

            status =
                "Bluetooth OFF - Please turn Bluetooth ON"

            return
        }


        val scanner =
            adapter.bluetoothLeScanner


        if (
            scanner == null
        ) {

            status =
                "BLE Scanner Unavailable"

            return
        }


        tagMap.clear()

        foundTags =
            emptyList()


        val settings =
            ScanSettings.Builder()
                .setScanMode(
                    ScanSettings
                        .SCAN_MODE_LOW_LATENCY
                )
                .build()


        scanner.startScan(
            null,
            settings,
            scanCallback
        )


        isScanning =
            true


        status =
            "Scanning Active [$scannerZone]"


        serverStatus =
            "Connecting..."


        startUploadLoop()
    }


    // ==================================================
    // Stop BLE Scan
    // ==================================================

    @SuppressLint("MissingPermission")
    private fun stopBleScan() {

        bluetoothAdapter
            ?.bluetoothLeScanner
            ?.stopScan(
                scanCallback
            )


        isScanning =
            false


        stopUploadLoop()


        tagMap.clear()

        foundTags =
            emptyList()


        status =
            "Scan Stopped"


        serverStatus =
            "Gateway stopped"
    }


    // ==================================================
    // Upload Loop
    // ==================================================

    private fun startUploadLoop() {

        uploadHandler
            .removeCallbacks(
                uploadRunnable
            )


        uploadHandler.post(
            uploadRunnable
        )
    }


    private fun stopUploadLoop() {

        uploadHandler
            .removeCallbacks(
                uploadRunnable
            )
    }


    // ==================================================
    // HTTP POST
    // ==================================================

    private fun postScanData(
        apiUrl: String,
        scannerId: String,
        tags: List<TagInfo>
    ) {

        var connection:
                HttpURLConnection? =
            null


        try {

            val tagsArray =
                JSONArray()


            tags.forEach { tag ->


                val tagJson =
                    JSONObject()


                tagJson.put(
                    "name",
                    tag.name
                )


                tagJson.put(
                    "address",
                    tag.address
                )


                tagJson.put(
                    "rssi",
                    tag.rssi
                )


                tagsArray.put(
                    tagJson
                )
            }


            val payload =
                JSONObject()


            payload.put(
                "scanner_id",
                scannerId
            )


            payload.put(
                "tags",
                tagsArray
            )


            connection =
                URL(
                    apiUrl
                )
                    .openConnection()
                        as HttpURLConnection


            connection.requestMethod =
                "POST"


            connection.connectTimeout =
                5000


            connection.readTimeout =
                5000


            connection.doOutput =
                true


            connection.setRequestProperty(
                "Content-Type",
                "application/json; charset=UTF-8"
            )


            val body =
                payload
                    .toString()
                    .toByteArray(
                        Charsets.UTF_8
                    )


            connection
                .outputStream
                .use { output ->

                    output.write(
                        body
                    )

                    output.flush()
                }


            val responseCode =
                connection
                    .responseCode


            if (
                responseCode
                in 200..299
            ) {

                connection
                    .inputStream
                    ?.close()

            } else {

                connection
                    .errorStream
                    ?.close()
            }


            runOnUiThread {

                serverStatus =
                    if (
                        responseCode
                        in 200..299
                    ) {

                        "HTTP $responseCode - Connected"

                    } else {

                        "HTTP $responseCode - Server Error"
                    }
            }


        } catch (
            e: Exception
        ) {


            runOnUiThread {

                serverStatus =
                    "${e.javaClass.simpleName}: ${e.message}"
            }


        } finally {


            connection
                ?.disconnect()
        }
    }
}