import SwiftUI
import AppKit

struct Item: Codable, Identifiable {
    let id: Int, title: String, category: String, is_active: Bool, points: Int
}
struct Branch: Codable, Identifiable {
    let id: String, title: String, children: [Branch]?, points: Int?
}
struct Job: Codable, Identifiable {
    var id: String { name }
    let name: String, domain: String, enabled: Bool, status: String?
}
struct Snapshot: Decodable {
    var running = false, autoStart = true
    var domains = [String](), jobs = [Job]()
    var tasks: [Item]?, tree: [Branch]?
}

@MainActor final class Store: ObservableObject {
    @Published var data = Snapshot(), busy = false, error = ""
    func request(_ action: String, _ values: [String: Any] = [:], then: (() -> Void)? = nil) {
        guard !busy else { return }
        busy = true
        error = ""
        let body = try! JSONSerialization.data(withJSONObject: values)
        let root = Bundle.main.object(forInfoDictionaryKey: "OmniCheckout") as! String
        Task {
            do {
                data = try await Task.detached {
                    let proc = Process(), out = Pipe(), input = Pipe()
                    proc.executableURL = URL(fileURLWithPath: root + "/.omni-local/api/bin/python")
                    proc.arguments = [root + "/scripts/desktop.py", action]
                    proc.environment = ["HOME": NSHomeDirectory(), "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"]
                    proc.standardInput = input
                    proc.standardOutput = out
                    try proc.run()
                    try input.fileHandleForWriting.write(contentsOf: body)
                    try input.fileHandleForWriting.close()
                    let bytes = out.fileHandleForReading.readDataToEndOfFile()
                    proc.waitUntilExit()
                    if proc.terminationStatus != 0 {
                        let detail = (try? JSONDecoder().decode([String:String].self, from: bytes))?["error"]
                        throw NSError(domain: "Omni", code: 1, userInfo: [NSLocalizedDescriptionKey: detail ?? "Could not reach this Omni installation."])
                    }
                    return try JSONDecoder().decode(Snapshot.self, from: bytes)
                }.value
                then?()
            } catch { self.error = error.localizedDescription }
            busy = false
        }
    }
}

struct TreeRow: View {
    let node: Branch
    var body: some View {
        Label {
            HStack {
                Text(node.title)
                Spacer()
                if let points = node.points { Text("\(points) pts").foregroundStyle(.secondary) }
            }
        } icon: {
            Image(systemName: node.children == nil ? "leaf" : "point.3.connected.trianglepath.dotted")
                .foregroundStyle(.green)
        }
    }
}

struct AtmaView: View {
    @ObservedObject var store: Store
    @State private var section = "Tasks", title = "", edited: Item?, revised = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Picker("View", selection: $section) {
                ForEach(["Tasks","History","World Tree"],id: \.self) { Text($0) }
            }.pickerStyle(.segmented).labelsHidden()
            if !store.data.running {
                Text("Omni is stopped.").font(.title2)
                Button("Start Omni") { store.request("startAtma") }
                Spacer()
            } else if section == "World Tree" {
                List(store.data.tree ?? [],children: \.children) { TreeRow(node:$0) }
            } else {
                if section == "Tasks" {
                    HStack {
                        TextField("What would you like to do?",text:$title).onSubmit { add() }
                        Button("Add task") { add() }.disabled(title.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                    }
                }
                let items = (store.data.tasks ?? []).filter { $0.is_active == (section == "Tasks") }
                if items.isEmpty {
                    Text(section == "Tasks" ? "Your first task starts here." : "Completed and archived tasks appear here.")
                        .foregroundStyle(.secondary).padding(.vertical)
                    Spacer()
                } else {
                    List(items) { task in
                        HStack(spacing: 12) {
                            if task.is_active {
                                Button { store.request("complete", ["id":task.id]) } label: {
                                    Image(systemName:"circle")
                                }.buttonStyle(.borderless).help("Complete task").accessibilityLabel("Complete " + task.title)
                            }
                            VStack(alignment:.leading) {
                                Text(task.title)
                                Text(task.category.capitalized).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if task.is_active {
                                Menu {
                                    Button("Rename") { revised = task.title; edited = task }
                                    Button("Archive") { store.request("archive",["id":task.id]) }
                                } label: { Image(systemName:"ellipsis") }.menuStyle(.borderlessButton).frame(width:32)
                            } else { Text("\(task.points) pts").foregroundStyle(.secondary) }
                        }.padding(.vertical,4)
                    }
                }
            }
        }.sheet(item:$edited) { task in
            VStack(alignment:.leading,spacing:16) {
                Text("Rename task").font(.headline)
                TextField("Task title",text:$revised)
                HStack {
                    Button("Cancel") { edited=nil }
                    Button("Save") { edited=nil; store.request("edit",["id":task.id,"title":revised]) }
                        .keyboardShortcut(.defaultAction).disabled(revised.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                }
            }.padding(24).frame(width:400)
        }
    }
    func add() {
        let value = title.trimmingCharacters(in:.whitespacesAndNewlines)
        if !value.isEmpty { store.request("add",["title":value]) { title="" } }
    }
}

struct OmniView: View {
    @ObservedObject var store: Store
    @State private var domain = "", selected = "atma", name = "", file: URL?
    var body: some View {
        Form {
            Section("Platform") {
                HStack {
                    Label(store.data.running ? "Running" : "Stopped",systemImage:"power")
                    Spacer()
                    Button(store.data.running ? "Stop Omni" : "Start Omni") { store.request(store.data.running ? "stop":"start") }
                }
                Toggle("Start Omni when I open Atma",isOn:Binding(get:{ store.data.autoStart },set:{store.request("autoStart",["enabled":$0])}))
                Button("Open Atma") {
                    NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory()+"/Applications/Atma.app"))
                }
            }
            Section("Domains") {
                ForEach(store.data.domains,id:\.self) { Text($0 == "atma" ? "Atma" : $0) }
                HStack {
                    TextField("New domain name",text:$domain)
                    Button("Add domain") { store.request("domain",["name":domain]) {domain=""} }.disabled(domain.isEmpty)
                }
            }
            Section("Automations") {
                if store.data.jobs.isEmpty { Text("No automations configured.").foregroundStyle(.secondary) }
                ForEach(store.data.jobs) { job in
                    HStack {
                        Toggle(job.name,isOn:Binding(get:{job.enabled},set:{store.request("enable",["name":job.name,"enabled":$0])}))
                        Spacer()
                        Text(job.domain + " · " + (job.status ?? "Idle")).foregroundStyle(.secondary)
                        Button("Run") { store.request("run",["name":job.name]) }.disabled(!store.data.running || !job.enabled || job.status == "running")
                    }
                }
                Picker("Domain",selection:$selected) {
                    ForEach(store.data.domains,id:\.self) { Text($0).tag($0) }
                }
                TextField("Automation name",text:$name)
                HStack {
                    Button(file?.lastPathComponent ?? "Choose executable…") {
                        let panel=NSOpenPanel()
                        if panel.runModal() == .OK {file=panel.url}
                    }
                    Spacer()
                    Button("Add automation") {
                        if let file { store.request("job",["name":name,"domain":selected,"path":file.path]) {name="";self.file=nil} }
                    }.disabled(file == nil || name.isEmpty)
                }
            }
        }.formStyle(.grouped)
    }
}

struct WindowContent: View {
    @StateObject var store = Store()
    let atma: Bool
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
            HStack {
                Text(atma ? "Atma" : "Omni").font(.largeTitle.weight(.semibold))
                Spacer()
                if store.busy { ProgressView().controlSize(.small) }
                Button { store.request(atma ? "tasks":"platform") } label: { Image(systemName:"arrow.clockwise") }.help("Refresh")
            }
            if !store.error.isEmpty { Text(store.error).foregroundStyle(.red).textSelection(.enabled) }
            Group {
                if atma { AtmaView(store:store) } else { OmniView(store:store) }
            }.disabled(store.busy)
        }.padding(22).frame(minWidth:520,minHeight:430)
        .task { store.request(atma ? "openAtma":"platform") }
    }
}

@main struct DesktopApp: App {
    var body: some Scene {
        WindowGroup { WindowContent(atma:Bundle.main.bundleIdentifier == "dev.omni.atma") }
    }
}
