// Is any process using the default microphone right now? (Phase 15B check.)
//
//   swift scripts/mic-in-use.swift            # prints a line at start and on every change
//   swift scripts/mic-in-use.swift --once     # prints the current state and exits
//
// Read-only: it asks Core Audio whether the default input device is running somewhere
// (kAudioDevicePropertyDeviceIsRunningSomewhere). It never opens or records the microphone.
import CoreAudio
import Foundation

func defaultInput() -> AudioDeviceID? {
    var device = AudioDeviceID(0)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultInputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &device)
    return status == noErr && device != 0 ? device : nil
}

func inUse(_ device: AudioDeviceID) -> Bool? {
    var running = UInt32(0)
    var size = UInt32(MemoryLayout<UInt32>.size)
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyDeviceIsRunningSomewhere,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    let status = AudioObjectGetPropertyData(device, &address, 0, nil, &size, &running)
    return status == noErr ? running != 0 : nil
}

let formatter = DateFormatter()
formatter.dateFormat = "HH:mm:ss.SSS"
func report(_ value: Bool?) {
    let text = value == nil ? "bilinmiyor" : (value! ? "EVET (mikrofon kullanımda)" : "HAYIR (mikrofon kapalı)")
    print("\(formatter.string(from: Date())) mikrofon kullanımda mı: \(text)")
    fflush(stdout)
}

guard let device = defaultInput() else {
    print("varsayılan mikrofon bulunamadı")
    exit(1)
}
var last = inUse(device)
report(last)
if CommandLine.arguments.contains("--once") { exit(0) }
while true {
    Thread.sleep(forTimeInterval: 0.25)
    let now = inUse(defaultInput() ?? device)
    if now != last {
        report(now)
        last = now
    }
}
