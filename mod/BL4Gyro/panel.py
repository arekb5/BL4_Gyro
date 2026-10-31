"""In-game gyro panel built from runtime UMG widgets."""
from __future__ import annotations
import sys
import time
import unrealsdk
from keybinds.keybinds import deregister_keybind, register_keybind
from mods_base import EInputEvent, get_pc
from unrealsdk import logging
from unrealsdk.hooks import Block, Type, add_hook, remove_hook
from . import state

FRAME_HOOK = "/Script/Engine.CameraModifier:BlueprintModifyCamera"
HOOK_ID = "bl4_gyro_panel"
TITLE = "BORDERLANDS 4 GYRO"
PAD_BITS = {"A":0,"B":1,"X":2,"Y":3,"View":4,"Menu":5,"L3":6,"R3":7,"LB":8,"RB":9,
            "D-pad Up":10,"D-pad Down":11,"D-pad Left":12,"D-pad Right":13,"LT":14,"RT":15}
COMBOS = {"L3 + R3":("L3","R3"),"LT + D-pad Up":("LT","D-pad Up"),"View + Menu":("View","Menu"),"LB + RB":("LB","RB"),"Off (F8 only)":()}
HOOK_KEYS = {"L3":"Gamepad_LeftThumbstick","R3":"Gamepad_RightThumbstick"}
PAD_NAV = {"D-pad Up":"up","D-pad Down":"down","D-pad Left":"left","D-pad Right":"right","A":"confirm","B":"back","LB":"fine_left","RB":"fine_right"}
KEY_NAV = {"Up":"up","Down":"down","Left":"left","Right":"right","Enter":"confirm","Escape":"back","BackSpace":"erase","Period":".","Comma":",","Decimal":".","Hyphen":"-","Subtract":"-",
           **{n:str(i) for i,n in enumerate(("Zero","One","Two","Three","Four","Five","Six","Seven","Eight","Nine"))},
           **{f"NumPad{n}":str(i) for i,n in enumerate(("Zero","One","Two","Three","Four","Five","Six","Seven","Eight","Nine"))}}
KEY_SWALLOW = (*"ABCDEFGHIJKLMNOPQRSTUVWXYZ","F1","F2","F3","F4","F5","F7","F8","F9","F10","F11","F12","Tab","CapsLock","LeftShift","RightShift","LeftControl","RightControl","LeftAlt","RightAlt","SpaceBar","Insert","Delete","Home","End","PageUp","PageDown","Pause","Tilde","Apostrophe","Quote","Semicolon","Slash","Backslash","LeftBracket","RightBracket","Equals","Add","Multiply","Divide","NumLock","LeftMouseButton","RightMouseButton","MiddleMouseButton","ThumbMouseButton","ThumbMouseButton2","MouseScrollUp","MouseScrollDown")
REPEATS = ("up","down","left","right","fine_left","fine_right")
MOUSE_AXES = ("MouseX","MouseY")
ROWS_SHOWN = 11
FONT_TITLE,FONT_ROW,FONT_HELP,FONT_FOOTER = 46,38,30,28
PANEL_W = 1840
HELP_H = 3 * FONT_HELP * 1.45
MARK_W,LABEL_W,VALUE_W = 50,800,900
ROW_PAD = 8
WHITE,DIM,ACCENT,BG = (0.95,0.95,0.95,1),(0.62,0.65,0.7,1),(1.0,0.78,0.2,1),(0.03,0.035,0.05,0.92)
_p = {"started":False,"open":False,"widget":None,"title":None,"rows":[],"help":None,"footer":None,"combo":state.Combo(()),"combo_handles":[],"key_handles":[],"repeat":state.Repeater(),"menu":None,"toast":None,"toast_until":0.0,"last_draw":0.0,"last_frame":0.0,"notified":set(),"actions":[],"buttons":0,"device":"pad","paused_by_us":False,"quickstart_closed":False}

def _g(): return sys.modules[__package__]
def held(name):
    bit=PAD_BITS.get(name); return bit is not None and bool(_p["buttons"] >> bit & 1)
def _color(rgba): return unrealsdk.make_struct("SlateColor",SpecifiedColor=unrealsdk.make_struct("LinearColor",R=rgba[0],G=rgba[1],B=rgba[2],A=rgba[3]))
def _margin(top=0,bottom=0): return unrealsdk.make_struct("Margin",Left=0,Top=top,Right=0,Bottom=bottom)
def _widget_class(name): return unrealsdk.find_class(name)
def _cw(tree, cls, name):
    """Use UWidgetTree.ConstructWidget: runtime widgets must be owned by the widget tree."""
    return tree.ConstructWidget(_widget_class(cls), name)
def _new_text(tree,size,rgba,name):
    t=_cw(tree,"TextBlock",name)
    try:
        font=t.Font; font.Size=size; t.SetFont(font)
    except Exception: pass
    t.SetColorAndOpacity(_color(rgba)); t.SetVisibility(0)
    return t
def _text(tree,box,size,rgba,name,gap=0,below=0):
    t=_new_text(tree,size,rgba,name); slot=box.AddChildToVerticalBox(t)
    if gap or below:
        try: slot.SetPadding(_margin(gap,below))
        except Exception: pass
    return t
def _column(tree,line,width,size,name,centered=False):
    box=_cw(tree,"SizeBox",name); box.SetWidthOverride(width)
    text=_new_text(tree,size,WHITE,name+"Text")
    if centered:
        try: text.SetJustification(1)
        except Exception: pass
    box.SetContent(text); line.AddChildToHorizontalBox(box); return text
def _row(tree,box,i):
    line=_cw(tree,"HorizontalBox",f"Row{i}"); slot=box.AddChildToVerticalBox(line)
    try: slot.SetPadding(_margin(ROW_PAD,ROW_PAD))
    except Exception: pass
    return line,_column(tree,line,MARK_W,FONT_ROW,f"Row{i}Mark"),_column(tree,line,LABEL_W,FONT_ROW,f"Row{i}Label"),_column(tree,line,VALUE_W,FONT_ROW,f"Row{i}Value",True)
def _widget(pc,width=None):
    lib=unrealsdk.find_class("WidgetBlueprintLibrary").ClassDefaultObject
    widget=lib.Create(pc,unrealsdk.find_class("UserWidget"),pc); tree=widget.WidgetTree
    border=_cw(tree,"Border","PanelBorder"); box=_cw(tree,"VerticalBox","PanelBox")
    if width is None: root=border
    else:
        root=_cw(tree,"SizeBox","PanelFrame"); root.SetWidthOverride(width); root.SetContent(border)
    tree.RootWidget=root; border.SetContent(box); border.SetBrushColor(unrealsdk.make_struct("LinearColor",R=BG[0],G=BG[1],B=BG[2],A=BG[3])); border.SetPadding(unrealsdk.make_struct("Margin",Left=40,Top=28,Right=40,Bottom=28)); root.SetVisibility(0)
    return widget,tree,box
def _show(widget,pc,anchor=(0.5,0.5)):
    widget.AddToViewport(100); layout=unrealsdk.find_class("WidgetLayoutLibrary").ClassDefaultObject; viewport=layout.GetViewportSize(pc)
    widget.SetAlignmentInViewport(unrealsdk.make_struct("Vector2D",X=anchor[0],Y=anchor[1])); widget.SetPositionInViewport(unrealsdk.make_struct("Vector2D",X=viewport.X*anchor[0],Y=viewport.Y*anchor[1]),True)
def _remove(w):
    if w is not None:
        try:w.RemoveFromParent()
        except Exception:pass
def _set(t,value,rgba=None):
    try:t.Text=value
    except Exception:pass
    t.SetText(value)
    if rgba is not None:t.SetColorAndOpacity(_color(rgba))
def _pad_labels():
    g=_g(); return state.pad_labels(g.button_labels.value,g.button_names(),g.status().split(" | ")[0])
def _hints(device):
    if device=="keyboard": return "Enter","Esc",{"slider":"Left/Right adjust   type a number + Enter","toggle":"Enter or Left/Right change","choice":"Left/Right change","action":"Enter run","section":"Enter open"}
    ok,back,left,right=_pad_labels(); return ok,back,{"slider":f"Left/Right adjust   {left}/{right} fine","toggle":f"{ok} or Left/Right change","choice":"Left/Right change","action":f"{ok} run","section":f"{ok} open"}
def _draw():
    if not _p["open"]: return
    menu=_p["menu"]; rows=menu.rows(); focus=menu.focused(); first=max(0,min(menu.index-ROWS_SHOWN//2,len(rows)-ROWS_SHOWN)); visible=rows[first:first+ROWS_SHOWN]
    _set(_p["title"],f"{TITLE} - {menu.section.upper()}",ACCENT)
    for i,(line,mark,label,value) in enumerate(_p["rows"]):
        shown=i<len(visible)
        try:line.SetVisibility(0 if shown else 1)
        except Exception:pass
        if not shown:continue
        row=visible[i]; focused=row is focus; val=menu.value_text(row)
        if row.kind in ("slider","toggle","choice") and focused and menu.entry is None: val=f"<   {val}   >"
        elif row.kind=="section":val=">>"
        rgba=ACCENT if focused else (DIM if row.kind=="info" else WHITE)
        _set(mark,">" if focused else "",rgba); _set(label,row.label,rgba); _set(value,val,rgba)
    confirm,back,footers=_hints(_p["device"])
    help_text=f"{menu.asking.confirm}   {confirm}: yes   {back}: no" if menu.asking is not None else (menu.message or (focus.help() if callable(focus.help) else focus.help))
    _set(_p["help"],help_text); _set(_p["footer"],f"{footers.get(focus.kind,'')}      {back} {'back' if menu.trail else 'close'}"); _p["last_draw"]=time.perf_counter()
def is_open(): return _p["open"]
def open(section=None): _p["request"]=("open",section)
def close(): _p["request"]=("close",None)
def toggle(): _p["request"]=("close" if _p["open"] else "open",None)
def _combo_callback(name):
    def cb(event):
        if event==EInputEvent.IE_Pressed:
            if _p["combo"].press(name,time.perf_counter()): _p.setdefault("combo_blocked",set()).add(name); return Block
        elif event==EInputEvent.IE_Repeat and name in _p.get("combo_blocked",set()): return Block
        elif event==EInputEvent.IE_Released: _p["combo"].release(name); _p.get("combo_blocked",set()).discard(name)
        return None
    return cb
def set_combo(name):
    for h in _p["combo_handles"]:deregister_keybind(h)
    _p["combo"]=state.Combo(COMBOS.get(name,COMBOS["L3 + R3"])); _p["combo_handles"]=[register_keybind(HOOK_KEYS[k],None,_combo_callback(k)) for k in _p["combo"].keys if k in HOOK_KEYS] if _p["started"] else []
def _use_device(d):
    if _p["device"]!=d:_p["device"]=d;_p["last_draw"]=0
def _pad(now):
    before,now_bits=_p["buttons"],_g().buttons();_p["buttons"]=now_bits
    for name,bit in PAD_BITS.items():
        was,down=before>>bit&1,now_bits>>bit&1
        if was==down:continue
        if name in _p["combo"].keys and name not in HOOK_KEYS: _p["combo"].press(name,now) if down else _p["combo"].release(name)
        if down:_use_device("pad")
        action=PAD_NAV.get(name)
        if _p["open"] and action:
            if down:
                _p["actions"].append(action)
                if action in REPEATS:_p["repeat"].press(name,now)
            else:_p["repeat"].release(name)
def _key_callback(key,action):
    def cb(event):
        if event==EInputEvent.IE_Pressed:_use_device("keyboard")
        if event==EInputEvent.IE_Released:_p["repeat"].release(key);return None
        if event==EInputEvent.IE_Pressed and action is not None:
            _p["actions"].append(action)
            if action in REPEATS:_p["repeat"].press(key,time.perf_counter())
        return Block
    return cb
def _mouse_callback(_):_use_device("keyboard")
def _act(action):
    m=_p["menu"]
    if action=="up":m.move(-1)
    elif action=="down":m.move(1)
    elif action in ("left","right","fine_left","fine_right"):m.adjust(-1 if "left" in action else 1,fine=action.startswith("fine"))
    elif action=="confirm":m.confirm()
    elif action=="back":
        if m.back():close();return
    elif action=="erase":m.erase()
    else:m.type_char(action)
    _draw()
def _apply_request():
    r=_p.pop("request",None)
    if r is not None: _open_now(r[1]) if r[0]=="open" else _close_now()
def _open_now(section=None):
    if _p["open"] or not _p["started"]:return
    pc=get_pc(possibly_loading=True)
    if pc is None:return
    statics=_g()._state["statics"]
    if pc.bShowMouseCursor or statics.IsGamePaused(pc):return
    if _p["menu"] is None:_p["menu"]=_build_menu()
    if section is not None:_p["menu"].section,_p["menu"].index,_p["menu"].trail=section,0,[];_p["menu"].move(0)
    try:
        widget,tree,box=_widget(pc,PANEL_W); title=_text(tree,box,FONT_TITLE,ACCENT,"Title",below=24); rows=[_row(tree,box,i) for i in range(ROWS_SHOWN)]
        help_area=_cw(tree,"SizeBox","HelpArea");help_area.SetHeightOverride(HELP_H);hs=box.AddChildToVerticalBox(help_area);hs.SetPadding(_margin(20,0));help_block=_new_text(tree,FONT_HELP,DIM,"Help");help_area.SetContent(help_block)
        try:help_block.SetAutoWrapText(True)
        except Exception:pass
        footer=_text(tree,box,FONT_FOOTER,DIM,"Footer",gap=10);_show(widget,pc)
    except Exception as e:
        logging.error(f"[BL4Gyro] could not open panel: {type(e).__name__}: {e}");return
    _p.update(open=True,widget=widget,title=title,rows=rows,rows_shown=[True]*len(rows),help=help_block,footer=footer,actions=[],pc=pc)
    keys=dict(KEY_NAV);panel_key=_g().open_panel_key.key;keys.update({k:None for k in KEY_SWALLOW if k not in keys and k!=panel_key})
    _p["key_handles"]=[register_keybind(k,None,_key_callback(k,a)) for k,a in keys.items()]+[register_keybind(k,None,_mouse_callback) for k in MOUSE_AXES]
    _p["paused_by_us"]=bool(statics.SetGamePaused(pc,True));pawn=pc.Pawn
    if pawn is not None:
        try:pawn.DisableInput(pc)
        except Exception:pass
    try:pc.DisableInput(pc)
    except Exception:pass
    _p["input_pawn"]=pawn
    if not _p["paused_by_us"]:
        try:pc.SetIgnoreMoveInput(True);pc.SetIgnoreLookInput(True)
        except Exception:pass
    _g().panel_changed();_draw()
def _close_now():
    if not _p["open"]:return
    _p["open"]=False
    for h in _p["key_handles"]:deregister_keybind(h)
    _p["key_handles"]=[];_p["repeat"]=state.Repeater();pc=_p.pop("pc",None);pawn=_p.pop("input_pawn",None)
    if pc is not None:
        try:pc.EnableInput(pc)
        except Exception:pass
        if pawn is not None:
            try:pawn.EnableInput(pc)
            except Exception:pass
        try:
            if _p["paused_by_us"]:_g()._state["statics"].SetGamePaused(pc,False)
            else:pc.SetIgnoreMoveInput(False);pc.SetIgnoreLookInput(False)
        except Exception:pass
    _p["paused_by_us"]=False;_remove(_p["widget"]);_p["widget"]=None
    if _p["menu"] is not None:_p["menu"].entry=_p["menu"].asking=None;_p["menu"].message=""
    _g().panel_changed();_g().save_now()
def _on_frame(_obj,_args,_ret,_func):
    now=time.perf_counter()
    if now-_p["last_frame"]<0.001:return
    _p["last_frame"]=now
    try:
        _pad(now)
        if _p["combo"].poll(now):toggle()
        _apply_request()
        if _p["open"]:
            actions,_p["actions"]=_p["actions"],[];r=_p["repeat"].poll(now)
            if r is not None:actions.append(r)
            for a in actions:
                try:_act(a)
                except Exception as e:logging.error(f"[BL4Gyro] panel action: {type(e).__name__}: {e}")
            _apply_request()
            if _p["open"] and now-_p["last_draw"]>0.25:_draw()
    except Exception as e:
        if not _p.get("frame_error"):_p["frame_error"]=True;logging.error(f"[BL4Gyro] panel update failed: {type(e).__name__}: {e}")
def start(combo_name):
    _p.update(started=True,notified=set(),buttons=0,combo_blocked=set());set_combo(combo_name);add_hook(FRAME_HOOK,Type.PRE,HOOK_ID,_on_frame)
def stop():
    _p.pop("request",None);_close_now();remove_hook(FRAME_HOOK,Type.PRE,HOOK_ID)
    for h in _p["combo_handles"]:deregister_keybind(h)
    _p["combo_handles"]=[];_remove(_p["toast"]);_p["toast"]=None;_p["started"]=False

def _option_row(option,kind,label=None,**extra):
    def setter(v):option.value=v
    if kind=="slider":extra.setdefault("lo",option.min_value);extra.setdefault("hi",option.max_value);extra.setdefault("step",option.step);extra.setdefault("fine",option.step/10 if option.step>=0.1 else option.step)
    if kind=="choice":extra.setdefault("choices",tuple(option.choices))
    extra.setdefault("help",option.description);return state.Row(label or option.display_name,kind,lambda:option.value,setter,**extra)
def _build_menu():
    g=_g();status=state.Row("Controller","info",lambda:g.status().split(" | ")[0]);menu=None
    def grouped():return bool(g.link_vertical.value)
    def individual():return not g.link_vertical.value
    def flick():return g.stick_mode.value=="Flick Stick"
    def calibrate(_):g.start_calibration()
    def intro(_):g.ui.value={**g.ui.value,"intro_seen":True}
    cal=state.Row("Calibrate now","action",set=calibrate,help="Hold the controller still or rest it on a table.")
    names=_option_row(g.button_labels,"choice")
    return state.Menu({
      "Main":[_option_row(g.gyro_enabled,"toggle","Gyro"),_option_row(g.pause_on_touchpad,"toggle"),_option_row(g.mode,"choice"),state.Row("Sensitivity","choice",lambda:"Grouped" if grouped() else "Individual",lambda v:setattr(g.link_vertical,"value",v=="Grouped"),choices=("Grouped","Individual")),_option_row(g.sens_x,"slider","Sensitivity (both directions)",fmt="{:.2f}",visible=grouped),_option_row(g.sens_x,"slider",fmt="{:.2f}",visible=individual),_option_row(g.sens_y,"slider",fmt="{:.2f}",visible=individual),_option_row(g.ads_multiplier,"slider",fmt="x{:.2f}",fine=0.01),cal,status,state.Row("Advanced","section",target="Advanced"),state.Row("Diagnostics","section",target="Diagnostics")],
      "Advanced":[_option_row(g.invert_x,"toggle"),_option_row(g.invert_y,"toggle"),_option_row(g.space,"choice"),_option_row(g.auto_calibrate,"toggle"),_option_row(g.smoothing,"slider",fine=0.1,fmt="{:.1f}"),_option_row(g.tighten,"slider",fine=0.1,fmt="{:.1f}"),_option_row(g.stick_mode,"choice"),_option_row(g.flick_time,"slider",fmt="{:.2f}",visible=flick),_option_row(g.flick_threshold,"slider",fmt="{:.2f}",fine=0.01,visible=flick),_option_row(g.gyro_button,"choice"),_option_row(g.combo,"choice"),names,_option_row(g.debug_trace,"toggle"),state.Row("Restore defaults","action",set=lambda _:g.restore_defaults())],
      "Diagnostics":[status,state.Row("Motion packets/s","info",lambda:f"{g.info()['packets']:.0f}"),state.Row("Gyro offset (deg/s)","info",lambda:"{:+.2f} {:+.2f} {:+.2f}".format(*g.info()["offset"])),state.Row("Camera hook","info",lambda:"stopped after errors" if g._state["stopped"] else "running"),state.Row("Game build","info",lambda:str(g._installed_build()))]
    })
