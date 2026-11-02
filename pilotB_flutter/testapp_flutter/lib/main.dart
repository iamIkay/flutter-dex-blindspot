// Pilot B ground-truth app (Flutter). Five benign behaviours, each behind a
// labelled button; the Kotlin twin in ../testapp_native implements the same.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_contacts/flutter_contacts.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

const String kPostUrl = 'https://httpbin.org/post';
const String kDummyKey = 'PILOT_DUMMY_KEY_123';
const String kFileName = 'pilot_file.txt';

void main() => runApp(const PilotApp());

class PilotApp extends StatelessWidget {
  const PilotApp({super.key});

  @override
  Widget build(BuildContext context) =>
      const MaterialApp(title: 'Pilot Flutter', home: PilotHome());
}

class PilotHome extends StatefulWidget {
  const PilotHome({super.key});

  @override
  State<PilotHome> createState() => _PilotHomeState();
}

class _PilotHomeState extends State<PilotHome> {
  String _output = 'Tap a button.';

  Future<void> _run(String label, Future<String> Function() action) async {
    String result;
    try {
      result = await action();
    } catch (e) {
      result = 'error: $e';
    }
    setState(() => _output = '$label → $result');
  }

  // B1: location (runtime permission).
  Future<String> _readLocation() async {
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) {
      perm = await Geolocator.requestPermission();
    }
    if (perm == LocationPermission.denied ||
        perm == LocationPermission.deniedForever) {
      return 'permission denied';
    }
    // LocationManager instead of Play Services' fused provider: matches the
    // native twin and avoids the Location Accuracy consent dialog. The plugin
    // ships both code paths in DEX either way.
    final pos = await Geolocator.getCurrentPosition(
      locationSettings: AndroidSettings(forceLocationManager: true),
    );
    return '${pos.latitude.toStringAsFixed(4)}, ${pos.longitude.toStringAsFixed(4)}';
  }

  // B2: contacts count only (runtime permission).
  Future<String> _readContactsCount() async {
    final status =
        await FlutterContacts.permissions.request(PermissionType.read);
    if (status != PermissionStatus.granted &&
        status != PermissionStatus.limited) {
      return 'permission denied';
    }
    final contacts = await FlutterContacts.getAll();
    return '${contacts.length} contacts';
  }

  // B3: HTTPS POST of a dummy JSON payload.
  Future<String> _postJson() async {
    final resp = await http.post(
      Uri.parse(kPostUrl),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'pilot': 'hello', 'n': 1}),
    );
    return 'HTTP ${resp.statusCode}';
  }

  // B4: write and read a file in app-private storage.
  Future<String> _fileRoundTrip() async {
    final dir = await getApplicationDocumentsDirectory();
    final file = File('${dir.path}/$kFileName');
    await file.writeAsString('pilot ${DateTime.now().toIso8601String()}');
    return 'read back: ${await file.readAsString()}';
  }

  // B5: hardcoded dummy API key, displayed masked.
  Future<String> _showMaskedKey() async {
    const key = kDummyKey;
    return '${key.substring(0, 4)}${'*' * (key.length - 7)}${key.substring(key.length - 3)}';
  }

  @override
  Widget build(BuildContext context) {
    final buttons = <(String, Future<String> Function())>[
      ('1. Read location', _readLocation),
      ('2. Count contacts', _readContactsCount),
      ('3. POST to httpbin', _postJson),
      ('4. File write/read', _fileRoundTrip),
      ('5. Show masked key', _showMaskedKey),
    ];
    return Scaffold(
      appBar: AppBar(title: const Text('Pilot B — Flutter')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final (label, action) in buttons)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: ElevatedButton(
                  onPressed: () => _run(label, action),
                  child: Text(label),
                ),
              ),
            const SizedBox(height: 16),
            Text(_output, key: const Key('output')),
          ],
        ),
      ),
    );
  }
}
