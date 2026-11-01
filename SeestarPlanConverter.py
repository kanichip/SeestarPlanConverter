# -*- coding: utf-8 -*-
"""N.I.N.A. Advanced Sequence -> Seestar ViewPlan, wxPython GUI."""
import json
import re
import threading
from datetime import datetime
from pathlib import Path

import wx

NINA_DEFAULT = ""
TARGET_ID_BASE = 800000000


def extract_panels(path):
    with Path(path).open("r", encoding="utf-8-sig") as f:
        root = json.load(f)

    found = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        kind = node.get("$type", "")
        if isinstance(kind, str) and kind.startswith(
            "NINA.Sequencer.Container.DeepSkyObjectContainer,"
        ):
            target = node.get("Target") or {}
            coords = target.get("InputCoordinates") or {}
            if not coords:
                raise ValueError("撮影ターゲットにInputCoordinatesがありません")
            name = target.get("TargetName") or node.get("Name") or ""
            match = re.search(r"(?:パネル|panel)\s*[-_#]?\s*(\d+)", name, re.I)
            number = int(match.group(1)) if match else len(found) + 1
            ra = (float(coords["RAHours"]) + float(coords["RAMinutes"]) / 60
                  + float(coords["RASeconds"]) / 3600)
            dec = (abs(float(coords["DecDegrees"])) + float(coords["DecMinutes"]) / 60
                   + float(coords["DecSeconds"]) / 3600)
            if coords.get("NegativeDec") or float(coords["DecDegrees"]) < 0:
                dec = -dec
            if not (0 <= ra < 24 and -90 <= dec <= 90):
                raise ValueError(f"座標が範囲外です: {name}")
            found.append((number, name, round(ra, 8), round(dec, 8)))
            return  # nested CenterAndRotate coordinates must not be counted
        items = node.get("Items")
        if isinstance(items, dict):
            walk(items.get("$values", []))
        elif isinstance(items, list):
            walk(items)

    walk(root)
    found.sort(key=lambda x: x[0])
    if not found:
        raise ValueError("N.I.N.A.の撮影ターゲットが見つかりません")
    nums = [p[0] for p in found]
    if len(nums) != len(set(nums)):
        raise ValueError(f"パネル番号が重複しています: {nums}")
    return found


def clock(total_minutes):
    days, within_day = divmod(total_minutes, 1440)
    suffix = f" (+{days}日)" if days else ""
    return f"{within_day // 60:02d}:{within_day % 60:02d}{suffix}"


def make_plan(panels, hour, minute, duration, plan_name):
    start = hour * 60 + minute
    if start + duration * len(panels) > 2880:
        raise ValueError("終了時刻が翌日24時を超えます。開始時刻か撮影時間を変更してください")
    items = []
    for i, (num, name, ra, dec) in enumerate(panels):
        items.append({
            "target_ra_dec": [ra, dec],
            "target_name": "M 45" if "M45" in plan_name.upper().replace(" ", "") else name,
            "alias_name": f"{plan_name}-P{num}",
            "lp_filter": False,
            "target_id": TARGET_ID_BASE + num,
            "camera_mode": "tele",
            "start_min": start + i * duration,
            "duration_min": duration,
            "skip": False,
        })
    return {
        "update_time_seestar": datetime.now().strftime("%Y.%m.%d"),
        "plan_name": plan_name,
        "plan_target_af": True,
        "viewplan_gohome": True,
        "list": items,
    }


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(
            None,
            title="N.I.N.A. → Seestar 撮影プラン転送",
            size=(600, 670)
        )

        self.ip = None
        self.panels = []
        self.current_plan = None
        self.busy = False
        self.alive = True

        self.InitUI()

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Centre()

        # 初期レイアウトを確定
        self.Layout()

        # 検索開始を300ms遅らせる
        wx.CallLater(300, self.search_scope)

    def InitUI(self):
        self.panel = wx.Panel(self)
        panel = self.panel

        outer = wx.BoxSizer(wx.VERTICAL)

        scope_row = wx.BoxSizer(wx.HORIZONTAL)
        scope_row.Add(wx.StaticText(panel, label="Seestar接続："), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.scope_label = wx.StaticText(panel, label="検索前")
        scope_row.Add(self.scope_label, 1, wx.ALIGN_CENTER_VERTICAL)
        self.search_button = wx.Button(panel, label="再検索")
        scope_row.Add(self.search_button, 0)
        outer.Add(scope_row, 0, wx.EXPAND | wx.ALL, 12)

        path_row = wx.BoxSizer(wx.HORIZONTAL)
        path_row.Add(wx.StaticText(panel, label="N.I.N.A. JSON："), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.file_ctrl = wx.TextCtrl(panel, value=str(NINA_DEFAULT), style=wx.TE_READONLY)
        path_row.Add(self.file_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.file_button = wx.Button(panel, label="ファイル選択...")
        path_row.Add(self.file_button, 0)
        outer.Add(path_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        settings = wx.BoxSizer(wx.HORIZONTAL)
        settings.Add(wx.StaticText(panel, label="開始時刻"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.hour = wx.SpinCtrl(panel, min=0, max=23, initial=20, size=(64, -1))
        self.minute = wx.Choice(panel, choices=[f"{i:02d}" for i in range(0, 60, 10)])
        self.minute.SetSelection(3)
        settings.Add(self.hour, 0, wx.RIGHT, 4)
        settings.Add(wx.StaticText(panel, label="："), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        settings.Add(self.minute, 0, wx.RIGHT, 24)
        settings.Add(wx.StaticText(panel, label="各パネル撮影時間"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        durations = [f"{i} 分" for i in range(10, 601, 10)]
        self.duration = wx.Choice(panel, choices=durations)
        self.duration.SetSelection(2)
        settings.Add(self.duration, 0, wx.RIGHT, 24)
        settings.Add(wx.StaticText(panel, label="プラン名"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.name_ctrl = wx.TextCtrl(panel, value="", size=(180, -1))
        settings.Add(self.name_ctrl, 1)
        outer.Add(settings, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        outer.Add(wx.StaticText(panel, label="撮影プラン（N.I.N.A.の座標を変更せず使用）"),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.table = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        columns = [
            ("パネル", 60),
            ("N.I.N.A.ターゲット", 110),
            ("赤経 RA（時）", 110),
            ("赤緯 Dec（度）", 110),
            ("開始", 100),
            ("撮影時間", 60)]
        for idx, (name, width) in enumerate(columns):
            self.table.InsertColumn(idx, name, width=width)
        outer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        self.summary = wx.StaticText(panel, label="JSONを選択してください")
        outer.Add(self.summary, 0, wx.ALL, 12)
        bottom = wx.BoxSizer(wx.HORIZONTAL)
        self.save_button = wx.Button(panel, label="JSONを保存")
        self.send_button = wx.Button(panel, label="Seestarへ転送")
        self.send_button.SetMinSize((170, 40))
        bottom.Add(self.save_button, 0, wx.RIGHT, 10)
        bottom.AddStretchSpacer()
        bottom.Add(self.send_button, 0)
        outer.Add(bottom, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.status = self.CreateStatusBar()
        panel.SetSizer(outer)

        self.file_button.Bind(wx.EVT_BUTTON, self.choose_file)
        self.search_button.Bind(wx.EVT_BUTTON, lambda event: self.search_scope())
        self.save_button.Bind(wx.EVT_BUTTON, self.save_json)
        self.send_button.Bind(wx.EVT_BUTTON, self.send_plan)
        self.hour.Bind(wx.EVT_SPINCTRL, self.rebuild)
        self.minute.Bind(wx.EVT_CHOICE, self.rebuild)
        self.duration.Bind(wx.EVT_CHOICE, self.rebuild)
        self.name_ctrl.Bind(wx.EVT_TEXT, self.rebuild)
        self.update_buttons()

    def show_error(self, message, title="エラー"):
        wx.MessageBox(str(message), title, wx.OK | wx.ICON_ERROR, self)

    def update_buttons(self):
        self.search_button.Enable(not self.busy)
        self.file_button.Enable(not self.busy)
        self.save_button.Enable(not self.busy and self.current_plan is not None)
        self.send_button.Enable(not self.busy and self.current_plan is not None and bool(self.ip))

    def search_scope(self):
        if self.busy:
            return
        self.busy = True
        self.ip = None
        self.scope_label.SetLabel("LAN内のSeestarを検索しています...")
        self.status.SetStatusText("UDPブロードキャストで検索中")
        self.update_buttons()

        def work():
            try:
                from seestarpy import connection as conn
                found = conn.discover(timeout=3, quiet=True)
                devices = []
                for sn, ip in sorted(found.items()):
                    rec = conn.DISCOVERED.get(sn, {})
                    model = rec.get("model", "Seestar")
                    devices.append((f"{model} / {ip} / {sn}", ip))
                wx.CallAfter(self.search_finished, devices, None)
            except Exception as exc:
                wx.CallAfter(self.search_finished, [], str(exc))

        threading.Thread(target=work, daemon=True).start()

    def search_finished(self, devices, error):
        if not self.alive:
            return
        self.busy = False
        if error or not devices:
            self.update_buttons()
            self.show_error(error or "LAN内にSeestarが見つかりません。\nWi-Fi/電源/同じLANを確認してください。",
                            "Seestarが見つかりません")
            self.Close()
            return
        if len(devices) > 1:
            with wx.SingleChoiceDialog(self, "接続先Seestarを選択してください", "機器選択",
                                       [d[0] for d in devices]) as dlg:
                if dlg.ShowModal() != wx.ID_OK:
                    self.Close()
                    return
                choice = dlg.GetSelection()
        else:
            choice = 0
        self.ip = devices[choice][1]
        self.scope_label.SetLabel(devices[choice][0])
        self.status.SetStatusText(f"Seestarを検出: {self.ip}")
        self.update_buttons()
        #if Path(self.file_ctrl.GetValue()).is_file():
        #    self.load_file(Path(self.file_ctrl.GetValue()))

    def choose_file(self, event):
        current = Path(self.file_ctrl.GetValue())
        with wx.FileDialog(self, "N.I.N.A.のシーケンスJSONを選択",
                           defaultDir=str(current.parent) if current.parent.is_dir() else "",
                           wildcard="JSONファイル (*.json)|*.json|すべてのファイル (*.*)|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                chosen = Path(dlg.GetPath())
                self.file_ctrl.SetValue(str(chosen))
                self.name_ctrl.SetValue(chosen.stem)
                self.load_file(chosen)

    def load_file(self, path):
        try:
            self.panels = extract_panels(path)
            self.rebuild()
            self.status.SetStatusText(f"N.I.N.A. JSON読み込み成功: {len(self.panels)}ターゲット")
        except Exception as exc:
            self.panels = []
            self.current_plan = None
            self.table.DeleteAllItems()
            self.update_buttons()
            self.show_error(exc, "JSONの読み込みに失敗")

    def get_output_path(self):
        val = self.file_ctrl.GetValue().strip()
        if not val:
            return None
        p = Path(val)
        return p.parent / f"SeestarPlan_{p.name}"

    def rebuild(self, event=None):
        if not self.panels:
            return
        try:
            duration = (self.duration.GetSelection() + 1) * 10
            minute = self.minute.GetSelection() * 10
            name = self.name_ctrl.GetValue().strip()
            if not name:
                raise ValueError("プラン名を入力してください")
            self.current_plan = make_plan(self.panels, self.hour.GetValue(), minute,
                                          duration, name)
            self.table.Freeze()
            try:
                self.table.DeleteAllItems()
                for i, (num, nina_name, ra, dec) in enumerate(self.panels):
                    target = self.current_plan["list"][i]
                    row = self.table.InsertItem(i, f"P{num}")
                    for col, value in enumerate([
                        nina_name, f"{ra:.8f}", f"{dec:+.8f}",
                        clock(target["start_min"]), f"{duration}分",
                    ], 1):
                        self.table.SetItem(row, col, value)
            finally:
                self.table.Thaw()
            end = self.current_plan["list"][-1]["start_min"] + duration
            output_path = self.get_output_path()
            output_str = str(output_path) if output_path else ""
            self.summary.SetLabel(
                f"合計 {len(self.panels)} パネル / {duration * len(self.panels)} 分"
                f"    開始 {clock(self.current_plan['list'][0]['start_min'])}"
                f"    終了 {clock(end)}"
                f"    出力: {output_str}"
            )
            self.status.SetStatusText("プラン生成済み（未転送）")
        except Exception as exc:
            self.current_plan = None
            self.summary.SetLabel(str(exc))
        self.update_buttons()

    def save_json(self, event=None):
        if self.current_plan is None:
            return False
        output_path = self.get_output_path()
        if not output_path:
            self.show_error("N.I.N.A.のJSONファイルが指定されていません", "JSON保存失敗")
            return False
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(self.current_plan, f, ensure_ascii=False, indent=2)
            self.status.SetStatusText(f"保存しました: {output_path}")
            return True
        except Exception as exc:
            self.show_error(exc, "JSON保存失敗")
            return False

    def send_plan(self, event):
        if self.busy or not self.ip or self.current_plan is None:
            return
        plan_data = json.loads(json.dumps(self.current_plan))
        count = len(plan_data["list"])
        first = clock(plan_data["list"][0]["start_min"])
        answer = wx.MessageBox(
            f"接続先: {self.ip}\nプラン: {plan_data['plan_name']}\n"
            f"撮影: {count}件 / {first}開始\n\n"
            "転送すると既存の実行プランが中断・置換される可能性があります。\n"
            "Seestar本体へ転送して実行しますか？",
            "転送の最終確認", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self,
        )
        if answer != wx.YES:
            return
        if not self.save_json():
            return
        self.busy = True
        self.update_buttons()
        self.status.SetStatusText("Seestarへ送信中...")
        ip = self.ip

        def work():
            try:
                from seestarpy import connection as conn
                from seestarpy import plan
                # Existing, successfully-tested transport is used without changes.
                conn.DEFAULT_IP = ip
                response = plan.set_view_plan(plan_data)
                if not isinstance(response, dict) or response.get("code") != 0 or response.get("result") != 0:
                    raise RuntimeError(f"送信APIが成功を返しませんでした: {response}")
                # Read the plan back to verify persistence and coordinates.
                actual = plan.get_running_plan()
                if not actual or "plan" not in actual:
                    raise RuntimeError("送信応答は成功ですが、プランを読み戻せませんでした")
                received = actual["plan"]
                if received.get("plan_name") != plan_data["plan_name"]:
                    raise RuntimeError("読み戻したプラン名が一致しません")
                a, b = plan_data["list"], received.get("list", [])
                if len(a) != len(b):
                    raise RuntimeError(f"ターゲット件数不一致: 送信{len(a)} / 本体{len(b)}")
                for i, (before, after) in enumerate(zip(a, b), 1):
                    if any(abs(x - y) > 0.00001 for x, y in zip(before["target_ra_dec"], after["target_ra_dec"])):
                        raise RuntimeError(f"パネル{i}の座標が本体と一致しません")
                message = (f"送信・読み戻し照合に成功しました。\n"
                           f"プラン: {received['plan_name']} / {len(b)}件\n"
                           f"本体の状態: {actual.get('state', '不明')}\n\n"
                           "撮影が正常に完了するかは、実撮影で確認してください。")
                wx.CallAfter(self.send_finished, True, message)
            except Exception as exc:
                wx.CallAfter(self.send_finished, False, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def send_finished(self, ok, message):
        if not self.alive:
            return
        self.busy = False
        self.update_buttons()
        self.status.SetStatusText("送信・読み戻し成功" if ok else "送信または照合に失敗")
        wx.MessageBox(message, "転送結果", wx.OK | (wx.ICON_INFORMATION if ok else wx.ICON_WARNING), self)

    def on_close(self, event):
        self.alive = False
        self.Destroy()


def main():
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()

    def fix_layout():
        frame.panel.SetSize(frame.GetClientSize())
        frame.panel.Layout()
        frame.panel.Refresh()

    wx.CallAfter(fix_layout)
    #wx.CallAfter(frame.SendSizeEvent)

    app.MainLoop()


if __name__ == "__main__":
    main()
