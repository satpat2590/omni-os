import SwiftUI
import AppKit

struct Item: Codable, Identifiable {
    let id: Int, title: String, category: String, is_active: Bool, points: Int
    let description: String?, classification_method: String?
}
struct Branch: Codable, Identifiable {
    let id: String, title: String, children: [Branch]?, points: Int?
}
struct Job: Codable, Identifiable {
    var id: String { name }
    let name: String, domain: String, enabled: Bool, status: String?
}
struct ClassificationReport: Decodable {
    var day: String?, state: String?, classified: Int?, pending: Int?, calls: Int?, errors: Int?
}
struct ClassifierSettings: Decodable {
    var mode: String, endpoint: String, model: String, limit: Int, daily: Bool, hasKey: Bool
    var currentState: String, idealState: String, shareContext: Bool, nlpReady: Bool
    var report: ClassificationReport
}
struct Snapshot: Decodable {
    var classifier: ClassifierSettings?

    var running = false, autoStart = true
    var domains = [String](), jobs = [Job]()
    var tasks: [Item]?, tree: [Branch]?
}

@MainActor final class Store: ObservableObject {
    @Published var data = Snapshot()
    @Published var busy = false
    @Published var error = ""
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
    @State private var section = "Tasks"
    @State private var title = ""
    @State private var edited: Item?
    @State private var revised = ""
    @State private var context = ""
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
                                Text(task.classification_method == "needs_context" ? "Needs context" : task.category.capitalized).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if task.is_active {
                                Menu {
                                    Button("Edit task") {
                                        revised = task.title
                                        context = task.description ?? ""
                                        edited = task
                                    }
                                    Button("Archive") { store.request("archive",["id":task.id]) }
                                } label: { Image(systemName:"ellipsis") }.menuStyle(.borderlessButton).frame(width:32)
                            } else { Text("\(task.points) pts").foregroundStyle(.secondary) }
                        }.padding(.vertical,4)
                    }
                }
            }
        }.sheet(item:$edited) { task in
            VStack(alignment:.leading,spacing:16) {
                Text("Edit task").font(.headline)
                TextField("Task title",text:$revised)
                TextField("What do you want to accomplish? (optional)",text:$context,axis:.vertical)
                    .lineLimit(2...5)
                HStack {
                    Button("Cancel") { edited=nil }
                    Button("Save") { edited=nil; store.request("edit",["id":task.id,"title":revised,"description":context]) }
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

struct ClassifierForm: View {
    @ObservedObject var store: Store
    let settings: ClassifierSettings
    @State private var mode: String
    @State private var endpoint: String
    @State private var model: String
    @State private var key = ""
    @State private var forget = false
    @State private var limit: Int
    @State private var daily: Bool
    @State private var currentState: String
    @State private var idealState: String
    @State private var shareContext: Bool

    init(store: Store, settings: ClassifierSettings) {
        self.store = store
        self.settings = settings
        _mode = State(initialValue:settings.mode)
        _endpoint = State(initialValue:settings.endpoint)
        _model = State(initialValue:settings.model)
        _limit = State(initialValue:settings.limit)
        _daily = State(initialValue:settings.daily)
        _currentState = State(initialValue:settings.currentState)
        _idealState = State(initialValue:settings.idealState)
        _shareContext = State(initialValue:settings.shareContext)
    }

    var body: some View {
        Section("Atma classification") {
            Picker("Classifier", selection:$mode) {
                Text("Static activities · offline").tag("static")
                Text("Local NLP · free").tag("offline")
                Text("Local NLP + API for uncertain tasks").tag("compatible")
                Text("API for all free-form tasks").tag("api")
            }
            if (mode == "offline" || mode == "compatible") && !settings.nlpReady {
                Button("Download offline NLP models (about 120 MB)") { store.request("installNLP") }
            }
            if mode != "static" {
                TextField("Current situation (optional)",text:$currentState,axis:.vertical)
                TextField("What do you want to work toward? (optional)",text:$idealState,axis:.vertical)
            }
            if mode == "compatible" || mode == "api" {
                TextField("API base URL",text:$endpoint)
                TextField("Model ID",text:$model)
                SecureField(settings.hasKey ? "Replace saved API key" : "API key (optional for local models)",text:$key)
                if settings.hasKey { Toggle("Forget saved key",isOn:$forget) }
                Toggle("Include my growth context in API requests",isOn:$shareContext)
                Stepper("Up to \(limit) model calls per pass",value:$limit,in:1...100)
                Text("Unresolved task titles, descriptions and candidate tags go to this endpoint. Use the model ID to choose your provider’s pricing tier.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Toggle("Classify daily at 3 AM",isOn:$daily)
            HStack {
                Button("Save settings") {
                    store.request("classifierSave",["mode":mode,"endpoint":endpoint,"model":model,"key":key,"forgetKey":forget,"daily":daily,"limit":limit,
                        "currentState":currentState,"idealState":idealState,"shareContext":shareContext]) {
                        key=""; forget=false
                        shareContext=store.data.classifier?.shareContext ?? false
                    }
                }
                Button("Classify now") { store.request("classify") }.disabled(!store.data.running)
            }
            if let state = settings.report.state {
                Text("Last pass: \(settings.report.day ?? "") · \(state) · \(settings.report.classified ?? 0) classified · \(settings.report.pending ?? 0) pending · \(settings.report.calls ?? 0) calls · \(settings.report.errors ?? 0) provider errors")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

struct OmniView: View {
    @ObservedObject var store: Store
    @State private var domain = ""
    @State private var selected = "atma"
    @State private var name = ""
    @State private var file: URL?
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
            if let settings = store.data.classifier { ClassifierForm(store:store,settings:settings) }
            Section("Domains") {
                ForEach(store.data.domains,id:\.self) { entry in
                    HStack {
                        Text(entry == "atma" ? "Atma" : entry)
                        Spacer()
                        if entry != "atma" {
                            Button("Remove") { store.request("removeDomain",["name":entry]) { selected="atma" } }
                                .disabled(store.data.jobs.contains { $0.domain == entry })
                        }
                    }
                }
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
                        Button { store.request("removeJob",["name":job.name]) } label: {Image(systemName:"minus.circle")}
                            .help("Remove automation").disabled(job.status == "running")
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
        .onReceive(Timer.publish(every: 4, on: .main, in: .common).autoconnect()) { _ in
            if !atma && store.data.running && (!store.data.jobs.isEmpty || store.data.classifier?.report.state == "running") && store.error.isEmpty && !store.busy {
                store.request("platform")
            }
        }
    }
}

@main struct DesktopApp: App {
    var body: some Scene {
        WindowGroup { WindowContent(atma:Bundle.main.bundleIdentifier == "dev.omni.atma") }
    }
}
