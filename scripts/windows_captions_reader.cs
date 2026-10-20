// Read-only bridge to Windows Live Captions. Method reference:
// SakiRinn/LiveCaptions-Translator (Apache-2.0), LiveCaptionsHandler.cs.
// No upstream implementation is copied. Only public UI Automation is used.
using System;
using System.Diagnostics;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Automation;

class WindowsCaptionsReader {
    static volatile bool stopping;
    static JavaScriptSerializer json = new JavaScriptSerializer();
    static void Send(object value) { Console.WriteLine(json.Serialize(value)); Console.Out.Flush(); }
    static int Main(string[] args) {
        Console.OutputEncoding = new UTF8Encoding(false);
        var input = new Thread(() => { try { Console.In.ReadToEnd(); } catch {} stopping = true; });
        input.IsBackground = true; input.Start();
        Process owned = null;
        Process source = null;
        AutomationElement window = null, caption = null;
        string last = null;
        int ticks = 0;
        try {
            var existing = Process.GetProcessesByName("LiveCaptions");
            if (existing.Length > 0) source = existing[0];
            else { owned = Process.Start(new ProcessStartInfo("LiveCaptions.exe") { UseShellExecute = true }); source = owned; }
            Send(new { kind = "waiting", owned_pid = owned == null ? 0 : owned.Id });
            while (!stopping) {
                Thread.Sleep(120);
                if (source == null || source.HasExited) { Send(new { kind = "closed" }); return 2; }
                try {
                    if (window == null) {
                        window = AutomationElement.RootElement.FindFirst(TreeScope.Children,
                            new AndCondition(
                                new PropertyCondition(AutomationElement.ProcessIdProperty, source.Id),
                                new PropertyCondition(AutomationElement.ClassNameProperty, "LiveCaptionsDesktopWindow")));
                    }
                    if (window == null) continue;
                    if (caption == null) caption = window.FindFirst(TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.AutomationIdProperty, "CaptionsTextBlock"));
                    if (caption == null) {
                        if (++ticks % 4 == 0) {
                            var ready = window.FindFirst(TreeScope.Descendants,
                                new PropertyCondition(AutomationElement.AutomationIdProperty, "ReadyToCaptionTextBlock"));
                            if (ready != null) Send(new { kind = "ready", text = "" });
                            else Send(new { kind = "setup" });
                        }
                        continue;
                    }
                    string text = caption.Current.Name ?? "";
                    // Heartbeats let the parent finalize idle text without audio callbacks.
                    if (text != last || ++ticks % 4 == 0) {
                        Send(new { kind = "snapshot", text = text }); last = text;
                    }
                } catch (ElementNotAvailableException) { window = caption = null; last = null; }
                  catch (InvalidOperationException) { window = caption = null; }
            }
            return 0;
        } catch { Send(new { kind = "error" }); return 1; }
        finally {
            // Never close a Live Captions session that was already running.
            if (owned != null) { try { if (!owned.HasExited) owned.CloseMainWindow(); } catch {} }
        }
    }
}
