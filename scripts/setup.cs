// GPL-3.0-only. Build with scripts/build_installer.py; no third-party binaries embedded.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class Setup : Form {
    readonly ComboBox language = new ComboBox(), mode = new ComboBox();
    readonly TextBox folder = new TextBox(), log = new TextBox();
    readonly CheckBox luna = new CheckBox(), shortcuts = new CheckBox(), open = new CheckBox();
    readonly Button install = new Button(), cancel = new Button();
    readonly Label note = new Label(), status = new Label(), locationLabel = new Label(), modeLabel = new Label();
    readonly ProgressBar progress = new ProgressBar();
    readonly TableLayoutPanel layout = new TableLayoutPanel();
    Process worker;
    bool busy, cancelled;
    string selectedLanguage = "en";

    string T(string en, string zh, string ja) { return selectedLanguage == "zh" ? zh : selectedLanguage == "ja" ? ja : en; }
    static string Quote(string value) { return "\"" + value.Replace("\\\"", "\\\\\"").TrimEnd('\\') + "\""; }
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

    [STAThread] static int Main(string[] args) {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        if (Array.IndexOf(args, "--quiet") >= 0) {
            try {
                string target = Value(args, "--target", null);
                if (target == null) throw new ArgumentException("--target is required");
                Extract(target);
                var command = StartCommand(target, Value(args,"--mode","windows"), Value(args,"--language","en"),
                    Array.IndexOf(args,"--with-luna")>=0, Value(args,"--cache-directory",null));
                using (Process process = Process.Start(command)) {
                    Task output = Pump(process.StandardOutput, Console.WriteLine);
                    Task errors = Pump(process.StandardError, Console.WriteLine);
                    process.WaitForExit(); Task.WaitAll(output,errors);
                    return process.ExitCode;
                }
            } catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
        }
        Application.Run(new Setup()); return 0;
    }
    static string Value(string[] args, string name, string fallback) {
        int index=Array.IndexOf(args,name); return index>=0 && index+1<args.Length ? args[index+1] : fallback;
    }
    Setup() {
        Text="Kitori — Setup"; ClientSize=new Size(760,610);
        MinimumSize=new Size(700,600); StartPosition=FormStartPosition.CenterScreen;
        Font=new Font("Segoe UI",10); Padding=new Padding(20);
        selectedLanguage=System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName;
        if(selectedLanguage!="zh" && selectedLanguage!="ja") selectedLanguage="en";
        layout.Dock=DockStyle.Fill; layout.ColumnCount=3; layout.RowCount=11;
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,120));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,95));
        for(int i=0;i<10;i++) layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent,100)); Controls.Add(layout);
        language.DropDownStyle=ComboBoxStyle.DropDownList;
        language.Items.AddRange(new object[]{"English","简体中文","日本語"});
        language.SelectedIndex=selectedLanguage=="zh"?1:selectedLanguage=="ja"?2:0;
        language.SelectedIndexChanged+=(s,e)=>{selectedLanguage=language.SelectedIndex==1?"zh":language.SelectedIndex==2?"ja":"en"; Localize();};
        Add(new Label{Text="Language / 语言 / 言語",AutoSize=true},0,0,1); Add(language,1,0,2);
        folder.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","Kitori");
        var browse=new Button{Text="…",AutoSize=true}; browse.Click+=(s,e)=>{using(var pick=new FolderBrowserDialog()){pick.SelectedPath=folder.Text;if(pick.ShowDialog(this)==DialogResult.OK)folder.Text=pick.SelectedPath;}};
        locationLabel.AutoSize=true;locationLabel.MaximumSize=new Size(115,0);modeLabel.AutoSize=true;
        Add(locationLabel,0,1,1);Add(folder,1,1,1);Add(browse,2,1,1);
        mode.DropDownStyle=ComboBoxStyle.DropDownList;
        Add(modeLabel,0,2,1);Add(mode,1,2,2);
        note.AutoSize=true;note.MaximumSize=new Size(700,0);note.Padding=new Padding(0,8,0,8);Add(note,0,3,3);
        luna.AutoSize=true;shortcuts.AutoSize=true;shortcuts.Checked=true;open.AutoSize=true;open.Checked=true;
        Add(luna,0,4,3);Add(shortcuts,0,5,3);Add(open,0,6,3);
        var license=new LinkLabel{Text="GPL-3.0 / Third-party notices",AutoSize=true};
        license.LinkClicked+=(s,e)=>ShowLicense();Add(license,0,7,3);
        var buttons=new FlowLayoutPanel{AutoSize=true,Dock=DockStyle.Fill};install.AutoSize=true;cancel.AutoSize=true;
        install.Click+=async(s,e)=>await Install();cancel.Click+=(s,e)=>{if(busy)Stop();else Close();};
        buttons.Controls.Add(install);buttons.Controls.Add(cancel);Add(buttons,0,8,3);
        progress.Dock=DockStyle.Fill;status.AutoSize=true;
        var row=new FlowLayoutPanel{AutoSize=true,Dock=DockStyle.Fill};row.Controls.Add(status);Add(row,0,9,3);
        log.Multiline=true;log.ReadOnly=true;log.ScrollBars=ScrollBars.Vertical;log.Dock=DockStyle.Fill;log.Font=new Font("Consolas",9);
        var bottom=new TableLayoutPanel{Dock=DockStyle.Fill,RowCount=2,ColumnCount=1};bottom.RowStyles.Add(new RowStyle(SizeType.Absolute,18));bottom.RowStyles.Add(new RowStyle(SizeType.Percent,100));bottom.Controls.Add(progress,0,0);bottom.Controls.Add(log,0,1);Add(bottom,0,10,3);
        Localize(); FormClosing+=(s,e)=>{if(busy){e.Cancel=true;Stop();}};
    }
    void Add(Control control,int column,int row,int span){control.Margin=new Padding(0,5,8,5);if(!(control is Label))control.Dock=DockStyle.Fill;layout.Controls.Add(control,column,row);layout.SetColumnSpan(control,span);}
    void Localize(){
        int selection=mode.SelectedIndex;
        mode.Items.Clear();mode.Items.AddRange(new object[]{T("Whisper turbo — NVIDIA GPU","Whisper turbo — NVIDIA 显卡","Whisper turbo — NVIDIA GPU"),T("Whisper small — CPU","Whisper small — CPU","Whisper small — CPU"),T("Windows Live Captions","Windows 实时字幕","Windows ライブ キャプション")});
        mode.SelectedIndex=selection<0?0:selection;
        locationLabel.Text=T("Install folder","安装目录","インストール先");modeLabel.Text=T("Recognition","识别方式","音声認識");
        note.Text=T("Internet required. Whisper downloads a 5.1 GB Tiger runtime plus a model (about 0.5–1.6 GB). Allow 20 GB free space. Windows Live Captions skips these downloads; enable its language pack in Windows. Python stays inside the selected folder. No administrator access required.","需要联网。Whisper 首次下载约 5.1 GB 运行库及 0.5–1.6 GB 模型，建议预留 20 GB 空间。Windows 实时字幕无需这些下载，但需在系统中启用语言包。Python 环境独立放在所选目录，不需要管理员权限。","ネット接続が必要です。Whisper は約5.1 GBの実行環境と0.5～1.6 GBのモデルをダウンロードします。空き容量は20 GBを推奨します。Windows の字幕を使う場合はこれらのダウンロードは不要ですが、言語パックの有効化が必要です。Python は選択したフォルダー内に置きます。管理者権限は不要です。");
        luna.Text=T("Also download LunaTranslator (optional, 67 MB)","同时准备 LunaTranslator（可选，67 MB）","LunaTranslator もダウンロード（任意、67 MB）");
        shortcuts.Text=T("Create desktop shortcuts","创建桌面快捷方式","デスクトップにショートカットを作成");
        open.Text=T("Open settings when finished","完成后打开设置","完了後に設定を開く");
        install.Text=T("Install","安装","インストール");cancel.Text=T("Close / Cancel","关闭 / 取消","閉じる / キャンセル");
        if(!busy)status.Text=T("Ready to install","准备安装","準備完了");
    }
    void Append(string value){if(IsDisposed||string.IsNullOrWhiteSpace(value))return;BeginInvoke(new Action(()=>log.AppendText(value+Environment.NewLine)));}
    static async Task Pump(StreamReader stream,Action<string> append){string line;while((line=await stream.ReadLineAsync())!=null)append(line);}
    static ProcessStartInfo StartCommand(string root,string mode,string language,bool luna,string cache){
        var start=new ProcessStartInfo("powershell.exe","-NoProfile -ExecutionPolicy Bypass -File "+Quote(Path.Combine(root,"scripts","install.ps1"))+" -Mode "+Quote(mode)+" -Language "+Quote(language)+(luna?" -WithLuna":"")+(cache==null?"":" -CacheDirectory "+Quote(cache)));
        start.WorkingDirectory=root;start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;start.RedirectStandardOutput=true;start.RedirectStandardError=true;start.StandardOutputEncoding=System.Text.Encoding.UTF8;start.StandardErrorEncoding=System.Text.Encoding.UTF8;return start;
    }
    static void Extract(string selected){
        string root=Path.GetFullPath(selected).TrimEnd(Path.DirectorySeparatorChar);
        if(root.Length<6 || root==Path.GetPathRoot(root).TrimEnd('\\'))throw new ArgumentException("Choose a dedicated application folder.");
        string marker=Path.Combine(root,".jcaption-install.json");
        if(Directory.Exists(root)&&Directory.GetFileSystemEntries(root).Length>0){
            if(!File.Exists(marker))throw new IOException("This folder is not empty. Choose a new folder; existing files will be kept.");
            var state=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(marker));
            if(!state.ContainsKey("status")||(string)state["status"]!="pending")throw new IOException("Already installed. Open Settings.cmd in this folder, or choose another folder.");
        }
        Directory.CreateDirectory(root);File.WriteAllText(marker,"{\"status\":\"pending\"}");
        using(var source=Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using(var archive=new ZipArchive(source,ZipArchiveMode.Read)){
            foreach(var entry in archive.Entries){
                string destination=Path.GetFullPath(Path.Combine(root,entry.FullName));
                if(!destination.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("Unsafe installation payload path.");
                if(entry.FullName.EndsWith("/")) {Directory.CreateDirectory(destination);continue;}
                Directory.CreateDirectory(Path.GetDirectoryName(destination));entry.ExtractToFile(destination,true);
            }
        }
    }
    async Task Install(){
        busy=true;cancelled=false;install.Enabled=false;language.Enabled=false;folder.Enabled=false;mode.Enabled=false;luna.Enabled=false;shortcuts.Enabled=false;open.Enabled=false;progress.Style=ProgressBarStyle.Marquee;
        status.Text=T("Installing…","正在安装…","インストール中…");
        string root=folder.Text;string choice=mode.SelectedIndex==0?"gpu":mode.SelectedIndex==1?"cpu":"windows";
        try{
            root=Path.GetFullPath(root);
            long required=choice=="windows"?2L*1024*1024*1024:20L*1024*1024*1024;
            if(new DriveInfo(Path.GetPathRoot(root)).AvailableFreeSpace<required)throw new IOException("Not enough disk space for this installation option.");
            Extract(root);worker=Process.Start(StartCommand(root,choice,selectedLanguage,luna.Checked,null));
            Task stdout=Pump(worker.StandardOutput,Append),stderr=Pump(worker.StandardError,Append);
            await Task.Run(()=>worker.WaitForExit());await Task.WhenAll(stdout,stderr);
            int code=worker.ExitCode;worker.Dispose();worker=null;
            if(cancelled)status.Text=T("Cancelled. Run setup again to resume.","已取消，可以再次运行安装器继续。","中止しました。再実行で続けられます。");
            else if(code!=0)throw new IOException("Installation failed. The log above shows the error. Run setup again to retry.");
            else{
                if(shortcuts.Checked)CreateShortcuts(root);
                status.Text=T("Installed","安装完成","インストール完了");
                if(open.Checked)Process.Start(new ProcessStartInfo(Path.Combine(root,"Settings.cmd")){UseShellExecute=true,WindowStyle=ProcessWindowStyle.Hidden});
            }
        }catch(Exception error){Append(error.Message);status.Text=T("Could not finish installation","安装未完成","インストール未完了");}
        finally{busy=false;progress.Style=ProgressBarStyle.Blocks;progress.Value=0;install.Enabled=true;language.Enabled=true;folder.Enabled=true;mode.Enabled=true;luna.Enabled=true;shortcuts.Enabled=true;open.Enabled=true;}
    }
    static void CreateShortcuts(string root){
        Type type=Type.GetTypeFromProgID("WScript.Shell");dynamic shell=Activator.CreateInstance(type);
        foreach(string item in new[]{"Start-Local","Settings","Stop"}){
            string label=item=="Start-Local"?"Kitori":item=="Settings"?"Kitori - Settings":"Kitori - Stop";
            dynamic shortcut=shell.CreateShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),label+".lnk"));
            shortcut.TargetPath=Path.Combine(root,item+".cmd");shortcut.WorkingDirectory=root;shortcut.WindowStyle=7;shortcut.Save();
        }
    }
    void Stop(){
        cancelled=true;if(worker==null||worker.HasExited)return;
        using(var killer=Process.Start(new ProcessStartInfo("taskkill.exe","/PID "+worker.Id+" /T /F"){UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden})){killer.WaitForExit();}
    }
    void ShowLicense(){
        using(var source=Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using(var archive=new ZipArchive(source,ZipArchiveMode.Read))
        using(var dialog=new Form{Text="GPL-3.0 and third-party notices",Size=new Size(760,600),StartPosition=FormStartPosition.CenterParent}){
            var text=new TextBox{Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill,Font=new Font("Consolas",9)};
            foreach(string name in new[]{"LICENSE","THIRD_PARTY.md"})using(var reader=new StreamReader(archive.GetEntry(name).Open()))text.AppendText(reader.ReadToEnd()+Environment.NewLine+Environment.NewLine);
            dialog.Controls.Add(text);dialog.ShowDialog(this);
        }
    }
}
