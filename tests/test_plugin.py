"""Local behavioral tests. Android/Telegram boundaries are simulated, no devices used."""

import ast
import copy
import hashlib
import io
import json
import math
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from uuid import uuid4


def load_plugin():
    tree = ast.parse((Path(__file__).parents[1] / "seven_tv_emojis.plugin").read_text())
    keep = {"_Emote", "SevenTvEmojisPlugin", "_SendHook", "_EntitiesHook",
            "_EmojiPagerHook", "_EmojiPanelHook", "_PickerSearch", "_PickerSearchTouch",
            "_PickerClick", "_PickerAdapter", "_EnterEmojiPanelHook"}
    tree.body = [
        item for item in tree.body
        if isinstance(item, (ast.Assign, ast.FunctionDef))
        or isinstance(item, ast.ClassDef) and item.name in keep
    ]
    env = dict(
        json=json, math=math, os=os, re=re, tempfile=tempfile, hashlib=hashlib,
        Path=Path, Request=Request, urlopen=urlopen, urlparse=urlparse,
        BasePlugin=object, MethodHook=object,
        uuid4=uuid4,
        Base=object, BaseAdapter=object, TextWatcher=object,
        java_subclass=lambda *_bases: lambda cls: cls,
        joverride=lambda: lambda method: method,
        dynamic_proxy=lambda _interface: object, jclass=lambda _name: object,
    )
    exec(compile(tree, "seven_tv_emojis.plugin", "exec"), env)
    return env


ENV = load_plugin()
Plugin = ENV["SevenTvEmojisPlugin"]
Emote = ENV["_Emote"]


class JList:
    """Java ArrayList boundary: only Java methods, no Python sequence protocol."""

    def __init__(self, values=()):
        self._items = list(values)

    def __iter__(self):
        raise TypeError("'Array list' object is not iterable")

    def add(self, value):
        self._items.append(value)

    def size(self):
        return len(self._items)

    def get(self, index):
        return self._items[index]

    def remove(self, item):
        self._items.remove(item)


def tl_class(name):
    class TL:
        def __init__(self):
            self.flags = 0
            self.attributes = JList()
            self.stickers = JList()
            self.documents = JList()
    TL.__name__ = name
    return TL


TL_NAMES = (
    "TL_messages_uploadMedia TL_inputPeerSelf TL_inputMediaUploadedDocument "
    "TL_documentAttributeSticker TL_inputStickerSetEmpty TL_messageMediaDocument "
    "TL_inputStickerSetItem TL_inputDocument TL_stickers_createStickerSet "
    "TL_inputUserSelf TL_stickers_addStickerToSet TL_inputStickerSetShortName "
    "TL_messages_stickerSet TL_documentAttributeCustomEmoji TL_messages_getStickerSet "
    "TL_messages_getMyStickers TL_messages_myStickers"
).split()
TL = NS(**{name: tl_class(name) for name in TL_NAMES})


class WeakRef:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class Annotation:
    pass


class ReplacementSpan:
    pass


class EmojiSpan(ReplacementSpan):
    def __init__(self, document_id, _metrics):
        self.document_id = document_id


class RichText:
    def __init__(self, value):
        self.text = str(value)
        self.spans = list(value.spans) if isinstance(value, RichText) else []

    def __str__(self):
        return self.text

    def length(self):
        return len(self.text.encode("utf-16-le")) // 2

    def subSequence(self, start, end):
        return self.text.encode("utf-16-le")[start * 2:end * 2].decode("utf-16-le")

    def getSpans(self, start, end, kind):
        return [span for span, first, last in self.spans
                if isinstance(span, kind) and first < end and last > start]

    def getSpanStart(self, span):
        return next((start for item, start, _end in self.spans if item is span), -1)

    def getSpanEnd(self, span):
        return next((end for item, _start, end in self.spans if item is span), -1)

    def setSpan(self, span, start, end, _flags):
        self.spans.append((span, start, end))

    def removeSpan(self, span):
        self.spans = [entry for entry in self.spans if entry[0] is not span]

    def append(self, value):
        offset = self.length()
        self.text += str(value)
        self.spans.extend((span, first + offset, last + offset)
                          for span, first, last in value.spans)

    def replace(self, start, end, value):
        value = RichText(value)
        new_spans = []
        delta = value.length() - (end - start)
        for span, first, last in self.spans:
            if last <= start:
                new_spans.append((span, first, last))
            elif first >= end:
                new_spans.append((span, first + delta, last + delta))
            elif first <= start and last >= end:
                new_spans.append((span, first, last + delta))
        new_spans.extend((span, first + start, last + start)
                         for span, first, last in value.spans)
        self.text = self.subSequence(0, start) + str(value) + self.subSequence(end, self.length())
        self.spans = new_spans


class Bitmap:
    Config = NS(ARGB_8888=1)
    CompressFormat = NS(PNG=1)
    fail_compress = False

    def __init__(self, pixels):
        self.pixels = pixels
        self.recycled = False

    def getWidth(self):
        return len(self.pixels[0])

    def getHeight(self):
        return len(self.pixels)

    def setDensity(self, density):
        assert density == 0

    @staticmethod
    def createBitmap(width, height, _config):
        return Bitmap([[0] * width for _ in range(height)])

    def compress(self, _format, _quality, stream):
        stream.write(json.dumps(self.pixels).encode())
        return not Bitmap.fail_compress

    def recycle(self):
        self.recycled = True


class Canvas:
    def __init__(self, bitmap):
        self.bitmap = bitmap

    def drawBitmap(self, source, x, y, _paint):
        assert int(x) == x and int(y) == y
        for row, values in enumerate(source.pixels):
            for col, value in enumerate(values):
                out_x, out_y = col + int(x), row + int(y)
                if 0 <= out_x < 100 and 0 <= out_y < 100:
                    self.bitmap.pixels[out_y][out_x] = value


class JavaInteger:
    """Boxed 32-bit Java integer, distinct from a Python int boxed as Long."""

    def __init__(self, value):
        self.value = int(value)

    def __int__(self):
        return self.value

    def __eq__(self, other):
        return self.value == int(other)


class JavaClass:
    def __init__(self, name, methods=(), parent=None):
        self.name, self.methods, self.parent = name, list(methods), parent

    def getName(self):
        return self.name

    def getDeclaredMethods(self):
        return self.methods

    def getSuperclass(self):
        return self.parent


class JavaMethod:
    def __init__(self, name, result, args=(), actual_name=None, owner="EmojiView$Obfuscated"):
        self.canonical = name
        self.name = actual_name or name
        self.result, self.args = result, args
        self.owner = owner

    def getName(self):
        return self.name

    def getReturnType(self):
        return JavaClass(self.result)

    def getParameterTypes(self):
        return [JavaClass(name) for name in self.args]

    def toGenericString(self):
        return f"{self.result} {self.owner}.{self.name}({','.join(self.args)})"

    def setAccessible(self, value):
        self.accessible = value


class Widget:
    """Minimal Android view boundary with real parenting and focus state."""

    VERTICAL = 1
    AUTO_FIT = -1
    STRETCH_COLUMN_WIDTH = 2
    LayoutParams = staticmethod(lambda *args: args)

    def __init__(self, context=None):
        self.context = context
        self.parent = None
        self.children = []
        self.focused = False
        self.text = ""

    def __getattr__(self, name):
        if name.startswith("set"):
            return lambda *args: setattr(self, name[3:], args[0] if len(args) == 1 else args)
        raise AttributeError(name)

    def getContext(self):
        return self.context

    def getParent(self):
        return self.parent

    def addView(self, child, *_params):
        if child.parent is not None:
            raise ValueError("View already has a parent")
        child.parent = self
        self.children.append(child)

    def removeView(self, child):
        self.children.remove(child)
        child.parent = None

    def setText(self, text):
        self.text = text

    def requestFocus(self):
        self.focused = True

    def clearFocus(self):
        self.focused = False

    def isFocused(self):
        return self.focused

    def addTextChangedListener(self, listener):
        self.watcher = listener


class HookParam:
    def __init__(self, owner, args=(), result=None, java_return=None):
        self.thisObject = owner
        self.args = args
        self.result = result
        self.replaced = False
        self.java_return = java_return

    def getResult(self):
        return self.result

    def setResult(self, result):
        if self.java_return == "int" and not isinstance(result, JavaInteger):
            raise TypeError("setResult(Object) boxes a Python int as Long, but Java returns int")
        self.result = result
        self.replaced = True


class TestPlugin(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.delayed = []
        self.requests = []
        self.uploads = []
        self.errors = []
        self.put_sets = []
        self.logs = []
        self.method_hooks = {}
        self.hooked_methods = []
        self.server_sets = {}
        self.users = {0: 100, 1: 200}
        self.config = NS(getInstance=lambda account: NS(
            getClientUserId=lambda: self.users[account], isPremium=lambda: True))
        loader = NS(uploadFile=lambda *args: self.uploads.append(args),
                    cancelFileUpload=lambda *args: None)

        def run_ui(callback, delay=0):
            if delay:
                self.delayed.append(callback)
            else:
                callback()

        self.env_patch = patch.dict(ENV, {
            "UserConfig": self.config, "System": NS(identityHashCode=id), "Integer": JavaInteger,
            "WeakReference": WeakRef, "Annotation": Annotation,
            "ReplacementSpan": ReplacementSpan, "SpannableStringBuilder": RichText,
            "SpannableString": RichText, "AnimatedEmojiSpan": EmojiSpan,
            "Spanned": NS(SPAN_EXCLUSIVE_EXCLUSIVE=33), "TLRPC": TL,
            "ConnectionsManager": NS(FileTypeFile=1),
            "NotificationCenter": NS(fileUploaded=1, fileUploadFailed=2),
            "get_file_loader": lambda _account: loader,
            "run_on_ui_thread": run_ui, "run_on_queue": lambda callback: callback(),
            "send_request": lambda request, callback, account: self.requests.append((request, callback, account)),
            "BulletinHelper": NS(show_error=self.errors.append),
            "MediaDataController": NS(getInstance=lambda _account: NS(putStickerSet=self.put_sets.append)),
            "Bitmap": Bitmap, "Canvas": Canvas,
            "TextView": Widget,
            "FileOutputStream": lambda path: open(path, "wb"),
            "get_private_field": lambda obj, name: getattr(obj.JA, name, None),
            "set_private_field": lambda obj, name, value: setattr(obj.JA, name, value) or True,
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.plugin = Plugin()
        p = self.plugin
        p._alive = p._enabled = True
        p._generation = 1
        p._storage = Path(self.temp.name)
        p._cache_path = p._storage / "documents.json"
        p._doc_cache = {"100": {"packs": [], "emotes": {}, "packs_checked": True}}
        for name in ("_emotes", "_editors", "_markers", "_visuals", "_pending",
                     "_waiting", "_queues", "_active", "_uploads", "_observers",
                     "_panels", "_panels_by_adapter", "_previews", "_media_accounts"):
            setattr(p, name, {})
        p._observe_uploads = lambda _account: None
        p._picker_adapter_hooks = set()

        def hook_method(method, handler):
            self.hooked_methods.append(method)
            self.method_hooks[method.canonical] = handler
            return NS(unhook=lambda: None)

        p.hook_method = hook_method
        p.log = self.logs.append
        self.emote = Emote("t2x2", "Wide", "01ABC", "", "")
        p._emotes = {"Wide": self.emote}
        p._emotes_by_code = {"Wide": [self.emote]}

    def composer(self, text="Wide", account=0):
        state = {"text": text, "reply": None, "edit": None, "dialog": 10, "shown": True}
        editor = NS(getText=lambda: state["text"], isShown=lambda: state["shown"])
        fragment = NS(getDialogId=lambda: state["dialog"], getThreadMessage=lambda: None)
        sent = []
        view = NS(messageEditText=editor, getParentFragment=lambda: fragment,
                  getReplyingMessageObject=lambda: state["reply"],
                  getEditingMessageObject=lambda: state["edit"], hasAudioToSend=lambda: False,
                  doneEditingMessage=lambda: sent.append("edit"),
                  JA=NS(replyingQuote=None, sendMessageInternal=lambda *args: sent.append(args)))
        watcher = NS(account=account, revision=0, choices={})
        self.plugin._editors[id(editor)] = watcher
        return state, view, watcher, sent

    def respond_media(self, document_id, snapshot=True):
        request, callback, account = self.requests.pop(0)
        self.assertIsInstance(request, TL.TL_messages_uploadMedia)
        self.assertEqual(request.media.mime_type, "image/png")
        response = TL.TL_messageMediaDocument()
        response.document = NS(id=document_id, access_hash=9, file_reference=b"ref")
        callback(response, None)
        if snapshot and self.requests and isinstance(self.requests[0][0], TL.TL_messages_getStickerSet):
            request, callback, _account = self.requests.pop(0)
            name = request.stickerset.short_name
            response = self.set_response(name, self.server_sets.get(name, []))
            callback(response, None)
        return account

    @staticmethod
    def emoji_document(document_id):
        attr = TL.TL_documentAttributeCustomEmoji()
        attr.alt = "🙂"
        return NS(id=document_id, attributes=JList([attr]))

    @staticmethod
    def set_response(name, documents):
        response = TL.TL_messages_stickerSet()
        response.set = NS(short_name=name, emojis=True, count=len(documents))
        response.documents = JList(documents)
        return response

    def respond_set(self, document_id, name="my_pack", reverse=False):
        request, callback, account = self.requests.pop(0)
        docs = self.server_sets.setdefault(name, [])
        if not any(doc.id == document_id for doc in docs):
            docs.append(self.emoji_document(document_id))
        response = self.set_response(name, list(reversed(docs)) if reverse else list(docs))
        callback(response, None)
        return request, account

    def finish_tile(self, path, document_id):
        self.plugin._on_upload_event(1, 0, [path, object()])
        self.respond_media(document_id)
        return self.respond_set(document_id)[0]

    def picker(self, text="", selection=None, registered=True):
        draft = RichText(text)
        selection = list(selection if selection is not None else (draft.length(), draft.length()))
        editor = Widget()
        editor.getText = lambda: draft
        editor.getSelectionStart = lambda: selection[0]
        editor.getSelectionEnd = lambda: selection[1]
        editor.setSelection = lambda value: selection.__setitem__(slice(None), [value, value])
        calls = []
        adapter = NS(notifyDataSetChanged=lambda: calls.append("notify"))
        methods = [
            JavaMethod("getCount", "int"),
            JavaMethod("getPageTitle", "java.lang.CharSequence", ("int",)),
            JavaMethod("getPageIconDrawable", "android.graphics.drawable.Drawable", ("int",)),
            JavaMethod("instantiateItem", "java.lang.Object", ("android.view.ViewGroup", "int")),
            JavaMethod("canScrollToTab", "boolean", ("int",)),
        ]
        parent = JavaClass("androidx.viewpager.widget.PagerAdapter", [
            JavaMethod("getItemPosition", "int", ("java.lang.Object",), owner="PagerAdapter")])
        runtime = JavaClass("org.telegram.ui.Components.EmojiView$a", methods, parent)
        adapter.getClass = lambda: runtime

        def get_count():
            param = HookParam(adapter, result=owner.JA.currentTabs.size(), java_return="int")
            handler = self.method_hooks.get("getCount")
            if handler is not None:
                handler.before_hooked_method(param)
            return int(param.result)

        adapter.getCount = get_count
        pager = NS(position=0)
        pager.getCurrentItem = lambda: pager.position
        pager.setCurrentItem = lambda position, _smooth: setattr(pager, "position", position)
        pager.setAdapter = lambda _adapter: calls.append("reset")
        pager.getAdapter = lambda: adapter
        strip = NS(setViewPager=lambda _pager: calls.append("tabs"))
        strip.JA = NS(tabCount=4)
        strip.fourth = Widget()
        strip.getTab = lambda position: strip.fourth if position == 3 and strip.JA.tabCount == 4 else None
        owner = Widget()
        enter = NS(messageEditText=editor, getEmojiView=lambda: owner)
        fragment = NS(getChatActivityEnterView=lambda: enter, getCurrentAccount=lambda: 0)
        enter.JA = NS(currentAccount=0)
        enter.getParentFragment = lambda: fragment
        owner.JA = NS(currentTabs=JList([0, 1, 2]), fragment=fragment,
                      pager=pager, typeTabs=strip, emojiPagerAdapter=adapter,
                      emojiBanned=False, delegate=NS(onSearchOpenClose=calls.append))
        state = {"owner_ref": WeakRef(owner), "enter_ref": WeakRef(enter),
                 "adapter_ref": WeakRef(adapter), "account": 0, "query": "",
                 "pager_ref": WeakRef(pager), "strip_ref": WeakRef(strip), "native_count": 3,
                 "items": [self.emote], "cells": {}}
        if registered:
            self.plugin._panels[id(owner)] = state
            self.plugin._panels_by_adapter[id(adapter)] = state
        return owner, state, draft, selection, calls

    def native_picker(self):
        """Native adapter and ViewPager observers which bypass every hook."""
        owner, state, _draft, _selection, calls = self.picker()
        root = Widget()
        state["root_ref"] = WeakRef(root)
        clazz = NS()

        class NativeTab:
            def __init__(self):
                self.JA = NS(type=None, view=None)

            def getClass(self):
                return clazz

        def create_tab(arguments):
            self.assertEqual(arguments, [owner])
            return NativeTab()

        constructor = NS(
            getParameterTypes=lambda: [NS(isInstance=lambda value: value is owner)],
            setAccessible=lambda value: self.assertTrue(value), newInstance=create_tab)
        clazz.getDeclaredConstructors = lambda: [constructor]
        native = [create_tab([owner]) for _index in range(3)]
        owner.JA.currentTabs = JList(native)
        adapter, pager, strip = owner.JA.emojiPagerAdapter, owner.JA.pager, owner.JA.typeTabs
        adapter.getCount = owner.JA.currentTabs.size
        pager.expected_count = 3

        def notify():
            calls.append("notify")
            pager.expected_count = adapter.getCount()

        def set_page(position, _smooth):
            self.assertEqual(pager.expected_count, adapter.getCount(), "ViewPager was not notified before populate")
            pager.position = position

        def reset(_adapter):
            calls.append("reset")
            pager.expected_count = adapter.getCount()
            pager.position = 0

        def rebuild(_pager):
            calls.append("tabs")
            strip.JA.tabCount = adapter.getCount()
            strip.fourth.setText("")  # Native getPageTitle(3) has no label.

        adapter.notifyDataSetChanged = notify
        pager.setCurrentItem, pager.setAdapter = set_page, reset
        strip.setViewPager = rebuild
        strip.JA.tabCount = 3
        return owner, state, native, calls

    def test_pager_int_results_use_boxed_integer_in_before_hook(self):
        owner, state, _draft, _selection, _calls = self.picker()
        adapter = owner.JA.emojiPagerAdapter
        param = HookParam(adapter, result=3, java_return="int")
        with self.assertRaises(TypeError):
            param.setResult(4)
        hook = ENV["_EmojiPagerHook"](self.plugin, "getCount")
        hook.method = NS()  # SDK metadata must not overwrite our operation.
        hook.before_hooked_method(param)
        self.assertIsInstance(param.result, JavaInteger)
        self.assertEqual(int(param.result), 4)
        root = Widget()
        state["root_ref"] = WeakRef(root)
        position = HookParam(adapter, [root], java_return="int")
        ENV["_EmojiPagerHook"](self.plugin, "getItemPosition").before_hooked_method(position)
        self.assertIsInstance(position.result, JavaInteger)
        self.assertEqual(int(position.result), -2)

    def test_native_fallback_adds_one_real_page_and_keeps_label_after_refresh(self):
        owner, state, native, _calls = self.native_picker()
        for _attempt in range(3):
            self.plugin._refresh_emoji_panel(owner)
            self.assertEqual(owner.JA.currentTabs.size(), 4)
            self.assertEqual(ENV["_java_list"](owner.JA.currentTabs)[:3], native)
            tab = owner.JA.currentTabs.get(3)
            self.assertIs(tab, state["native_tab_ref"].get())
            self.assertIsInstance(tab.JA.type, JavaInteger)
            self.assertEqual(int(tab.JA.type), 3)
            self.assertIs(tab.JA.view, state["root_ref"].get())
            self.assertEqual(owner.JA.typeTabs.fourth.text, "7TV")
            self.assertEqual(owner.JA.typeTabs.fourth.ContentDescription, "7TV")
            self.assertEqual(self.plugin._picker_status, "Подключена: 4 вкладки")
        self.assertEqual(state.get("count_hook_hits", 0), 0)
        self.assertEqual(sum("added native fourth Tab" in message for message in self.logs), 1)

    def test_native_fallback_disable_notifies_pager_before_returning_to_first_page(self):
        owner, state, native, calls = self.native_picker()
        self.plugin._refresh_emoji_panel(owner)
        owner.JA.pager.setCurrentItem(3, False)
        calls.clear()
        self.plugin._on_enabled(False)
        self.assertEqual(ENV["_java_list"](owner.JA.currentTabs), native)
        self.assertEqual(owner.JA.typeTabs.JA.tabCount, 3)
        self.assertEqual(owner.JA.pager.position, 0)
        self.assertEqual(calls, ["notify", "tabs"])
        self.assertNotIn("native_tab_ref", state)
        self.assertEqual(self.plugin._picker_status, "Скрыта: плагин выключен")
        self.plugin._on_enabled(True)
        self.assertEqual(owner.JA.currentTabs.size(), 4)
        self.assertEqual(self.plugin._picker_status, "Подключена: 4 вкладки")

    def test_native_fallback_unload_removes_own_tab_when_hooks_already_gone(self):
        owner, state, native, calls = self.native_picker()
        self.plugin._refresh_emoji_panel(owner)
        owner.JA.pager.setCurrentItem(3, False)
        self.method_hooks.clear()
        calls.clear()
        self.plugin.on_plugin_unload()
        self.assertEqual(ENV["_java_list"](owner.JA.currentTabs), native)
        self.assertEqual(owner.JA.typeTabs.JA.tabCount, 3)
        self.assertEqual(owner.JA.pager.position, 0)
        self.assertEqual(calls, ["reset", "tabs"])
        self.assertNotIn("native_tab_ref", state)
        self.assertEqual(self.plugin._panels, {})

    def test_native_fallback_follows_chat_page_restrictions_without_count_hook(self):
        owner, state, native, _calls = self.native_picker()
        self.plugin._refresh_emoji_panel(owner)
        # Native setAllow rebuilds its list and drops our Tab when chat restrictions change.
        owner.JA.currentTabs = JList(native[:2])
        owner.JA.emojiPagerAdapter.getCount = lambda: owner.JA.currentTabs.size()
        self.plugin._refresh_emoji_panel(owner)
        self.assertEqual(owner.JA.currentTabs.size(), 2)
        self.assertEqual(state["native_count"], 2)
        self.assertEqual(self.plugin._picker_status, "Штатных страниц: 2")
        owner.JA.currentTabs = JList(native)
        self.plugin._refresh_emoji_panel(owner)
        self.assertEqual(owner.JA.currentTabs.size(), 4)
        self.assertEqual(self.plugin._picker_status, "Подключена: 4 вкладки")

    def test_native_fallback_field_failure_does_not_append_partial_page(self):
        owner, state, native, _calls = self.native_picker()
        with patch.dict(ENV, {"set_private_field": lambda *_args: False}):
            self.plugin._refresh_emoji_panel(owner)
        self.assertEqual(ENV["_java_list"](owner.JA.currentTabs), native)
        self.assertNotIn("native_tab_ref", state)
        self.assertIn("Не удалось заполнить страницу 7TV", self.plugin._picker_status)

    def test_native_fallback_does_not_remove_another_fourth_page(self):
        owner, _state, native, _calls = self.native_picker()
        extra = NS(JA=NS())
        owner.JA.currentTabs.add(extra)
        self.plugin._refresh_emoji_panel(owner)
        self.assertEqual(self.plugin._picker_status, "Штатных страниц: 4")
        self.plugin._on_enabled(False)
        self.assertEqual(ENV["_java_list"](owner.JA.currentTabs), native + [extra])

    def test_fourth_tab_preserves_native_pages_and_reuses_custom_view(self):
        owner, state, _draft, _selection, _calls = self.picker()
        adapter = owner.JA.emojiPagerAdapter
        count = HookParam(adapter, result=3)
        ENV["_EmojiPagerHook"](self.plugin, "getCount").before_hooked_method(count)
        self.assertEqual(count.result, 4)
        for method in ("getPageTitle", "getPageIconDrawable", "canScrollToTab"):
            hook = ENV["_EmojiPagerHook"](self.plugin, method)
            for position in range(3):
                param = HookParam(adapter, [position])
                hook.before_hooked_method(param)
                self.assertFalse(param.replaced)
        title = HookParam(adapter, [3])
        ENV["_EmojiPagerHook"](self.plugin, "getPageTitle").before_hooked_method(title)
        self.assertEqual(title.result, "7TV")
        root = Widget()
        state["root_ref"] = WeakRef(root)
        first, second = Widget(), Widget()
        hook = ENV["_EmojiPagerHook"](self.plugin, "instantiateItem")
        for parent in (first, first, second):
            param = HookParam(adapter, [parent, 3])
            hook.before_hooked_method(param)
            self.assertIs(param.result, root)
            self.assertEqual(parent.children, [root])
        self.assertEqual(first.children, [])
        other = HookParam(NS(), result=3)
        ENV["_EmojiPagerHook"](self.plugin, "getCount").before_hooked_method(other)
        self.assertEqual(other.result, 3)
        self.assertEqual(ENV["_java_list"](owner.JA.currentTabs), [0, 1, 2])

    def test_picker_is_gated_by_premium_enabled_and_three_native_pages(self):
        owner, state, draft, _selection, _calls = self.picker()
        for condition in ("premium", "enabled", "alive", "tabs", "collected"):
            with self.subTest(condition=condition):
                self.plugin._alive = self.plugin._enabled = True
                owner.JA.currentTabs = JList([0, 1, 2])
                state["owner_ref"].value = owner
                config = self.config
                if condition == "premium":
                    config = NS(getInstance=lambda _account: NS(isPremium=lambda: False))
                elif condition == "enabled":
                    self.plugin._enabled = False
                elif condition == "alive":
                    self.plugin._alive = False
                elif condition == "tabs":
                    owner.JA.currentTabs = JList([0, 2])
                    state["native_count"] = 2
                else:
                    state["owner_ref"].value = None
                if condition != "tabs":
                    state["native_count"] = 3
                with patch.dict(ENV, {"UserConfig": config}):
                    count = HookParam(owner.JA.emojiPagerAdapter, result=owner.JA.currentTabs.size())
                    ENV["_EmojiPagerHook"](self.plugin, "getCount").before_hooked_method(count)
                    self.plugin._pick_emote(state, 0)
                self.assertEqual(count.result, 2 if condition == "tabs" else 3)
                self.assertEqual(str(draft), "")
        self.assertEqual(self.uploads, [])

    def test_picker_search_filters_codes_channels_and_refreshes_loaded_items(self):
        _owner, state, _draft, _selection, _calls = self.picker()
        self.plugin._emotes.update({
            ")": Emote("bratishkinoff", ")", "02", "", ""),
            "KEKW": Emote("t2x2", "KEKW", "03", "", ""),
        })
        status = Widget()
        state["status_ref"] = WeakRef(status)
        refreshes = []
        peer = ENV["_PickerAdapter"](self.plugin, state)
        peer.java = NS(notifyDataSetChanged=lambda: refreshes.append(peer.getCount()))
        state["grid_adapter"] = peer
        listener = ENV["_PickerSearch"](self.plugin, state)
        listener.afterTextChanged(" T2X2 ")
        self.assertEqual([item.code for item in state["items"]], ["KEKW", "Wide"])
        self.assertEqual(status.text, "Смайлов: 2")
        listener.afterTextChanged("wid")
        self.assertEqual(peer.getItem(0), "Wide")
        self.plugin._emotes["WideTwo"] = Emote("other", "WideTwo", "04", "", "")
        self.plugin._refresh_picker_content(state)
        self.assertEqual(peer.getCount(), 2)
        self.assertEqual(state["query"], "wid")
        listener.afterTextChanged("absent")
        self.assertEqual(peer.getCount(), 0)
        self.assertEqual(status.text, "Ничего не найдено")
        listener.afterTextChanged("")
        self.assertEqual([item.code for item in state["items"]], [")", "KEKW", "Wide", "WideTwo"])
        self.assertEqual(refreshes, [2, 1, 2, 0, 4])

    def test_picker_inserts_at_utf16_caret_replaces_selection_and_separates_tokens(self):
        cases = [
            ("", None, "Wide ", 5),
            ("😀", None, "😀 Wide ", 8),
            ("a b", (1, 1), "a Wide b", 6),
            ("ab", (1, 1), "a Wide b", 7),
            ("😀 old next", (6, 3), "😀 Wide next", 7),
            ("a\n", (-1, -1), "a\nWide ", 7),
        ]
        for text, selection, expected, caret in cases:
            with self.subTest(text=text, selection=selection):
                _owner, state, draft, actual_selection, _calls = self.picker(text, selection)
                ENV["_PickerClick"](self.plugin, state).onItemClick(None, None, 0, 0)
                self.assertEqual(str(draft), expected)
                self.assertEqual(actual_selection, [caret, caret])
                self.assertEqual(len(list(self.plugin._matches(str(draft)))), 1)
                self.assertTrue(state["enter_ref"].get().messageEditText.isFocused())
        self.assertEqual(self.uploads, [])
        self.assertEqual(self.errors, [])

    def test_stale_picker_never_inserts_into_another_chat(self):
        _owner, state, draft, _selection, _calls = self.picker("draft")
        state["enter_ref"].get().getEmojiView = Widget
        self.plugin._pick_emote(state, 0)
        self.plugin._pick_emote(state, -1)
        self.plugin._pick_emote(state, 20)
        self.assertEqual(str(draft), "draft")
        self.assertEqual(self.uploads, [])

    def test_disabling_picker_restores_native_tab_and_closes_keyboard(self):
        owner, state, _draft, _selection, calls = self.picker()
        root, search = Widget(), Widget()
        state["root_ref"], state["search_ref"] = WeakRef(root), WeakRef(search)
        search.requestFocus()
        owner.JA.pager.position = 3
        hidden = []
        with patch.dict(ENV, {"AndroidUtilities": NS(hideKeyboard=hidden.append)}):
            self.plugin._on_enabled(False)
        self.assertEqual(owner.JA.pager.position, 0)
        self.assertFalse(search.isFocused())
        self.assertEqual(hidden, [search])
        self.assertEqual(calls, [0, "notify", "tabs"])
        custom = HookParam(owner.JA.emojiPagerAdapter, [root])
        native = HookParam(owner.JA.emojiPagerAdapter, [Widget()])
        hook = ENV["_EmojiPagerHook"](self.plugin, "getItemPosition")
        hook.before_hooked_method(custom)
        hook.before_hooked_method(native)
        self.assertEqual(custom.result, -2)
        self.assertFalse(native.replaced)

    def test_picker_registration_is_idempotent_and_collected_panels_are_removed(self):
        owner, _state, _draft, _selection, calls = self.picker(registered=False)
        self.plugin._attach_emoji_panel(owner)
        self.plugin._attach_emoji_panel(owner)
        self.assertEqual(len(self.plugin._panels), 1)
        self.assertEqual(calls, ["notify", "tabs", "notify", "tabs"])
        state = self.plugin._panels[id(owner)]
        state["owner_ref"].value = None
        self.plugin._refresh_emoji_panels()
        self.assertEqual(self.plugin._panels, {})
        self.assertEqual(self.plugin._panels_by_adapter, {})

    def test_missing_named_inner_adapter_does_not_disable_popup_registration(self):
        owner, _state, _draft, _selection, _calls = self.picker(registered=False)
        classes = {"org.telegram.ui.Components.EmojiView": JavaClass("EmojiView"),
                   "org.telegram.ui.Components.ChatActivityEnterView": JavaClass("EnterView")}
        requested, handlers = [], {}

        def find_class(name):
            requested.append(name)
            return classes.get(name)

        def hook_all_methods(clazz, name, handler):
            handlers[(clazz.getName(), name)] = handler
            return [NS()]

        self.plugin.hook_all_constructors = lambda *_args: [NS()]
        self.plugin.hook_all_methods = hook_all_methods
        with patch.dict(ENV, {"find_class": find_class}):
            self.plugin._setup_picker_hooks()
        self.assertNotIn("org.telegram.ui.Components.EmojiView$EmojiPagesAdapter", requested)
        self.assertNotIn("androidx.viewpager.widget.PagerAdapter", requested)
        enter = owner.JA.fragment.getChatActivityEnterView()
        handlers[("EnterView", "showPopup")].after_hooked_method(HookParam(enter))
        self.assertEqual(owner.JA.pager.getAdapter().getCount(), 4)
        self.assertEqual(self.plugin._picker_status, "Подключена: 4 вкладки")
        self.assertEqual(len(self.hooked_methods), 6)

    def test_popup_registration_reads_inherited_fields_without_ja_or_fragment(self):
        owner, _state, draft, _selection, _calls = self.picker(registered=False)
        enter = owner.JA.fragment.getChatActivityEnterView()
        native = owner.JA
        fields = {id(owner): {"pager": native.pager, "typeTabs": native.typeTabs},
                  id(enter): {"currentAccount": 0}, id(native.typeTabs): {"tabCount": 4}}
        owner.JA = NS()  # Anonymous subclass does not declare the base fields.
        reads = []

        def get_private_field(obj, name):
            reads.append((id(obj), name))
            return fields.get(id(obj), {}).get(name)

        def count():
            param = HookParam(native.emojiPagerAdapter, result=3)
            handler = self.method_hooks.get("getCount")
            if handler is not None:
                handler.before_hooked_method(param)
            return int(param.result)

        native.emojiPagerAdapter.getCount = count
        with patch.dict(ENV, {"get_private_field": get_private_field}):
            ENV["_EnterEmojiPanelHook"](self.plugin).after_hooked_method(HookParam(enter))
            self.assertEqual(count(), 4)
            state = self.plugin._panels[id(owner)]
            self.plugin._pick_emote(state, 0)
        self.assertEqual(str(draft), "Wide ")
        self.assertEqual(reads[:3], [(id(owner), "pager"), (id(owner), "typeTabs"),
                                    (id(enter), "currentAccount")])
        self.assertIn((id(native.typeTabs), "tabCount"), reads)
        self.assertEqual(self.plugin._picker_status, "Подключена: 4 вкладки")

    def test_runtime_adapter_hooks_find_renamed_methods_and_inherited_position(self):
        owner, _state, _draft, _selection, _calls = self.picker(registered=False)
        adapter = owner.JA.emojiPagerAdapter
        runtime = adapter.getClass()
        for index, method in enumerate(runtime.methods):
            method.name = f"renamed{index}"
        self.plugin._attach_emoji_panel(owner)
        self.assertEqual(adapter.getCount(), 4)
        self.assertEqual(len(self.hooked_methods), 6)
        inherited = next(method for method in self.hooked_methods if method.canonical == "getItemPosition")
        self.assertEqual(inherited.owner, "PagerAdapter")
        self.plugin._hook_picker_adapter(adapter)
        self.assertEqual(len(self.hooked_methods), 6)
        self.assertTrue(all(method.accessible for method in self.hooked_methods))

    def test_failed_adapter_hook_keeps_three_pages_and_next_popup_retries(self):
        owner, _state, _draft, _selection, _calls = self.picker(registered=False)
        original = self.plugin.hook_method

        def fail_title(method, handler):
            return None if method.canonical == "getPageTitle" else original(method, handler)

        self.plugin.hook_method = fail_title
        self.plugin._attach_emoji_panel(owner)
        self.assertEqual(owner.JA.emojiPagerAdapter.getCount(), 3)
        self.assertEqual(self.plugin._panels, {})
        self.assertIn("getPageTitle", self.plugin._picker_status)
        self.plugin.hook_method = original
        enter = owner.JA.fragment.getChatActivityEnterView()
        ENV["_EnterEmojiPanelHook"](self.plugin).after_hooked_method(HookParam(enter))
        self.assertEqual(owner.JA.emojiPagerAdapter.getCount(), 4)
        self.assertEqual(self.plugin._picker_status, "Подключена: 4 вкладки")
        self.assertEqual(len(self.hooked_methods), 6)

    def test_picker_status_checks_visible_tabs_not_only_adapter_count(self):
        owner, _state, _draft, _selection, _calls = self.picker(registered=False)
        owner.JA.typeTabs.JA.tabCount = 3
        self.plugin._attach_emoji_panel(owner)
        self.assertEqual(owner.JA.emojiPagerAdapter.getCount(), 4)
        self.assertEqual(self.plugin._picker_status, "Адаптер: 4; панель показала 3 вкладки")

    def test_panel_is_registered_after_factory_assignment_not_during_construction(self):
        owner, _state, _draft, _selection, _calls = self.picker(registered=False)
        enter = owner.JA.fragment.getChatActivityEnterView()
        enter.getEmojiView = lambda: None
        self.plugin._attach_emoji_panel(owner)
        self.assertEqual(self.plugin._panels, {})
        self.assertEqual(self.hooked_methods, [])
        enter.getEmojiView = lambda: owner
        ENV["_EnterEmojiPanelHook"](self.plugin).after_hooked_method(HookParam(enter))
        self.assertEqual(owner.JA.emojiPagerAdapter.getCount(), 4)
        self.assertEqual(self.plugin._picker_status, "Подключена: 4 вкладки")

    def test_unload_restores_pager_on_ui_thread_even_after_hooks_are_removed(self):
        owner, state, _draft, _selection, calls = self.picker()
        owner.JA.pager.position = 3
        callbacks = []
        with patch.dict(ENV, {"run_on_ui_thread": callbacks.append}):
            self.plugin.on_plugin_unload()
        self.assertFalse(self.plugin._alive)
        self.assertEqual(calls, [])
        self.assertEqual(len(callbacks), 1)
        callbacks.pop()()
        self.assertEqual(calls, ["reset", "tabs"])
        self.assertEqual(owner.JA.pager.position, 0)
        self.assertEqual(self.plugin._panels, {})
        self.assertEqual(self.plugin._panels_by_adapter, {})
        self.assertEqual(state["items"], [])
        self.assertFalse(any("failed" in message for message in self.logs))

    def test_picker_builds_virtual_grid_and_loads_only_bound_previews(self):
        _owner, state, _draft, _selection, _calls = self.picker()
        dp = NS(dp=lambda value: value)
        theme = NS(getColor=lambda value: value, key_chat_emojiPanelBackground=1,
                   key_windowBackgroundWhiteBlackText=2, key_windowBackgroundWhiteGrayText=3)
        adapter_class = ENV["_PickerAdapter"]

        def new_adapter(*, init_args):
            peer = adapter_class(*init_args)
            peer.java = NS(notifyDataSetChanged=lambda: None)
            return peer

        loaded = []
        self.plugin._load_preview = loaded.append
        self.plugin._emotes.update({str(i): Emote("t2x2", str(i), str(i), "", "") for i in range(1000)})
        with patch.dict(ENV, {
            "AndroidUtilities": dp, "LinearLayout": Widget, "AndroidEditText": Widget,
            "TextView": Widget, "GridView": Widget, "Theme": theme,
            "Gravity": NS(CENTER=1), "TextUtils": NS(TruncateAt=NS(END=1)),
            "jclass": lambda _name: Widget.LayoutParams,
        }), patch.object(adapter_class, "new_instance", new_adapter, create=True):
            root = self.plugin._ensure_picker_page(state)
            self.assertIs(root, self.plugin._ensure_picker_page(state))
            self.assertEqual(len(root.children), 3)
            self.assertEqual(loaded, [])
            peer = state["grid_adapter"]
            self.assertEqual(peer.getCount(), 1001)
            parent = state["grid_ref"].get()
            cell = peer.getView(0, None, parent)
            self.assertEqual(len(loaded), 1)
            cell_again = peer.getView(1, cell, parent)
            self.assertIs(cell, cell_again)
            self.assertEqual(len(state["cells"]), 1)
            self.assertEqual(len(loaded), 2)
            record = next(iter(state["cells"].values()))
            self.assertIs(record["emote"], state["items"][1])
            self.assertEqual(str(record["label_ref"].get().text), state["items"][1].code)
        rebound = []
        self.plugin._bind_picker_preview = rebound.append
        self.plugin._refresh_picker_previews(state["items"][0].emote_id)
        self.assertEqual(rebound, [])
        self.plugin._refresh_picker_previews(state["items"][1].emote_id)
        self.assertEqual(rebound, [record])

    def test_picker_search_notifies_native_keyboard_layout_and_closes_after_insertion(self):
        owner, state, draft, _selection, calls = self.picker()
        search = Widget()
        state["search_ref"] = WeakRef(search)
        shown, hidden = [], []
        with patch.dict(ENV, {"AndroidUtilities": NS(showKeyboard=shown.append, hideKeyboard=hidden.append),
                              "MotionEvent": NS(ACTION_DOWN=0)}):
            touch = ENV["_PickerSearchTouch"](self.plugin, state)
            self.assertFalse(touch.onTouch(search, NS(getActionMasked=lambda: 1)))
            self.assertEqual(shown, [])
            self.assertFalse(touch.onTouch(search, NS(getActionMasked=lambda: 0)))
            self.assertEqual(calls, [1])
            self.assertTrue(search.isFocused())
            self.assertEqual(shown, [search])
            self.plugin._pick_emote(state, 0)
            self.assertEqual(str(draft), "Wide ")
            self.assertEqual(calls, [1, 0])
            self.assertEqual(hidden, [search])
            search.requestFocus()
            hook = ENV["_EmojiPanelHook"](self.plugin, close_search=True)
            hook.after_hooked_method(HookParam(owner))
            self.assertFalse(search.isFocused())
            self.assertEqual(hidden, [search, search])
        self.assertEqual(self.errors, [])

    def test_channels_deduplicate_and_reject_invalid(self):
        self.assertEqual(ENV["_channels"]("t2x2, BRATISHKINOFF t2x2\n@bad\na/../b"),
                         ["t2x2", "bratishkinoff"])

    def test_picker_listeners_import_with_direct_dynamic_proxy_bases(self):
        class InterfaceMeta(type):
            def __new__(meta, name, bases, namespace):
                if any(isinstance(base, InterfaceMeta) for base in bases):
                    raise TypeError("dynamic_proxy must be used first in class bases")
                return super().__new__(meta, name, bases, namespace)

        class RawInterface(metaclass=InterfaceMeta):
            pass

        class ProxyBase:
            pass

        requested = []

        def jclass(name):
            requested.append(name)
            return RawInterface

        def dynamic_proxy(interface):
            self.assertIs(interface, RawInterface)
            return ProxyBase

        tree = ast.parse((Path(__file__).parents[1] / "seven_tv_emojis.plugin").read_text())
        names = {"_PickerClick", "_PickerSearch", "_PickerSearchTouch"}
        tree.body = [item for item in tree.body
                     if isinstance(item, ast.ClassDef) and item.name in names]
        namespace = dict(jclass=jclass, dynamic_proxy=dynamic_proxy, TextWatcher=RawInterface)
        exec(compile(tree, "seven_tv_emojis.plugin", "exec"), namespace)
        for name in names:
            self.assertIsInstance(namespace[name](self.plugin, {}), ProxyBase)
        self.assertEqual(requested, ["android.widget.AdapterView$OnItemClickListener",
                                     "android.view.View$OnTouchListener"])

    def test_upload_observer_uses_direct_dynamic_proxy_and_forwards_java_arguments(self):
        # Reproduce the import-time restriction rather than replacing this class
        # with a plain object, which would hide invalid Java-interface inheritance.
        class InterfaceMeta(type):
            def __new__(meta, name, bases, namespace):
                if any(isinstance(base, InterfaceMeta) for base in bases):
                    raise TypeError("dynamic_proxy must be used first in class bases")
                return super().__new__(meta, name, bases, namespace)

        class RawInterface(metaclass=InterfaceMeta):
            pass

        class ProxyBase:
            pass

        requested = []

        def jclass(name):
            requested.append(name)
            return RawInterface

        def dynamic_proxy(interface):
            self.assertIs(interface, RawInterface)
            return ProxyBase

        tree = ast.parse((Path(__file__).parents[1] / "seven_tv_emojis.plugin").read_text())
        tree.body = [item for item in tree.body
                     if isinstance(item, ast.ClassDef) and item.name == "_UploadObserver"]
        namespace = dict(jclass=jclass, dynamic_proxy=dynamic_proxy,
                         NotificationCenterDelegate=RawInterface)
        exec(compile(tree, "seven_tv_emojis.plugin", "exec"), namespace)
        self.assertEqual(requested, ["org.telegram.messenger.NotificationCenter$NotificationCenterDelegate"])
        calls = []
        observer = namespace["_UploadObserver"](NS(_on_upload_event=lambda *args: calls.append(args)))
        payload = ["tile.png", object()]
        observer.didReceivedNotification(1, 0, payload)
        self.assertEqual(calls, [(1, 0, payload)])

    def test_exact_tokens_need_no_trigger(self):
        self.assertEqual([(start, end) for start, end, _emote in self.plugin._matches("😀 Wide\nWide !Wide WideX")],
                         [(2, 6), (7, 11)])
        self.assertEqual(ENV["_utf16_offsets"]("😀Wide"), [0, 2, 3, 4, 5, 6])

    def test_choose_real_cdn_rendition_and_matching_animation(self):
        images = [dict(mime="image/png", frameCount=1, height=h, width=h * 3,
                       scale=i, url=f"png{i}") for i, h in enumerate((32, 64, 96, 128), 1)]
        images += [dict(mime="image/gif", frameCount=20, height=h, width=h * 3,
                        scale=i, url=f"gif{i}") for i, h in enumerate((32, 64, 96, 128), 1)]
        source, preview = ENV["_choose_images"](images)
        animation, animated_preview = ENV["_choose_animation"](images, source)
        self.assertEqual((source["url"], preview["url"], animation["url"], animated_preview["url"]),
                         ("png3", "png1", "gif3", "gif1"))

    def test_first_send_creates_pack_all_tiles_then_reuses_cache(self):
        p = self.plugin
        p._prepare_tiles = lambda _emote: ["one.png", "two.png"]
        _state, view, _watcher, sent = self.composer()
        self.assertTrue(p._defer_send(view, (True, 0, 0, 0, True), False))
        self.assertTrue(p._defer_send(view, (True, 0, 0, 0, True), False))
        self.assertEqual(len(self.uploads), 1)
        create = self.finish_tile("one.png", 1001)
        self.assertIsInstance(create, TL.TL_stickers_createStickerSet)
        self.assertTrue(create.emojis)
        self.assertEqual(sent, [])
        add = self.finish_tile("two.png", 1002)
        self.assertIsInstance(add, TL.TL_stickers_addStickerToSet)
        self.assertEqual(add.stickerset.short_name, "my_pack")
        self.assertEqual(sent, [(True, 0, 0, 0, True)])
        self.assertFalse(p._defer_send(view, (), False))
        self.assertEqual(len(self.uploads), 2)
        self.assertEqual(p._cached_tiles(0, "01ABC"), [(1001, "🙂"), (1002, "🙂")])
        self.assertEqual(len(self.put_sets), 2)
        self.assertEqual(json.loads(p._cache_path.read_text())["100"]["emotes"]["01ABC"][1]["id"], 1002)
        for timeout in self.delayed:
            timeout()
        self.assertEqual(self.errors, [])

    def test_partial_upload_resumes_without_duplicate_first_tile(self):
        p = self.plugin
        p._prepare_tiles = lambda _emote: ["one.png", "two.png"]
        _state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        self.finish_tile("one.png", 1001)
        p._on_upload_event(2, 0, ["two.png"])
        self.assertEqual(sent, [])
        self.assertIsNone(p._cached_tiles(0, "01ABC"))
        p._defer_send(view, (), False)
        self.assertEqual([entry[0] for entry in self.uploads], ["one.png", "two.png", "two.png"])
        self.finish_tile("two.png", 1002)
        self.assertEqual(len(sent), 1)

    def test_first_pack_has_explicit_valid_title_short_name_and_emoji_flags(self):
        p = self.plugin
        p._prepare_tiles = lambda _emote: ["one.png"]
        _state, view, _watcher, _sent = self.composer()
        p._defer_send(view, (), False)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1001)
        request, _callback, _account = self.requests[0]
        self.assertEqual(request.title, "SevenTV Emotes")
        self.assertTrue(1 <= len(request.title) <= 64)
        self.assertRegex(request.short_name, r"\A[A-Za-z][A-Za-z0-9_]{0,63}\Z")
        self.assertNotIn("__", request.short_name)
        self.assertEqual(request.flags, 32)
        self.assertTrue(request.emojis)
        self.assertFalse(request.masks)
        self.assertEqual(request.stickers.get(0).document.id, 1001)

    def test_long_parenthesis_uses_returned_emoji_ids_and_sends_all_fragments(self):
        p = self.plugin
        self.emote.code = ")"
        p._emotes = {")": self.emote}
        p._emotes_by_code = {")": [self.emote]}
        # The live 7TV ')' rendition is 192x96: exactly two native-pixel tiles.
        pixels = [[row * 192 + col + 1 for col in range(192)] for row in range(96)]
        (p._storage / "source_01ABC.png").touch()
        self.enterContext(patch.dict(ENV, {"BitmapFactory": NS(decodeFile=lambda _path: Bitmap(copy.deepcopy(pixels)))}))
        _state, view, _watcher, sent = self.composer(")")
        p._defer_send(view, (), False)
        mutations = []
        paths = [str(p._storage / f"tile_01ABC_{index}.png") for index in range(2)]
        for index, path in enumerate(paths):
            self.assertEqual(sent, [])
            self.assertEqual(self.uploads[-1][0], path)
            p._on_upload_event(1, 0, [path, object()])
            self.respond_media(1001 + index)
            request, _account = self.respond_set(5001 + index, reverse=True)
            mutations.append(type(request).__name__)
        self.assertEqual(mutations, ["TL_stickers_createStickerSet", "TL_stickers_addStickerToSet"])
        self.assertEqual(p._cached_tiles(0, "01ABC"), [(5001, "🙂"), (5002, "🙂")])
        self.assertEqual(len(p._account_cache(0)["packs"]), 1)
        self.assertEqual(p._account_cache(0)["packs"][0]["count"], 2)
        self.assertEqual(len(sent), 1)

    def test_three_orphan_packs_are_discovered_and_reused_without_creating_fourth(self):
        p = self.plugin
        p._account_cache(0).pop("packs_checked")
        p._prepare_tiles = lambda _emote: ["one.png", "two.png", "three.png"]
        _state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        request, callback, _account = self.requests.pop(0)
        self.assertIsInstance(request, TL.TL_messages_getMyStickers)
        self.assertEqual(self.uploads, [])
        response = TL.TL_messages_myStickers()
        response.sets = JList()
        # An unrelated owned pack must not be selected.
        response.sets.add(NS(set=NS(id=99, short_name="personal", title="Other", emojis=True, count=1)))
        for index, name in enumerate(("SevenTV_a", "SevenTV_b", "SevenTV_c")):
            response.sets.add(NS(set=NS(id=index + 1, short_name=name, title="SevenTV Emotes", emojis=True, count=1)))
            self.server_sets[name] = [self.emoji_document(4001 + index)]
        callback(response, None)
        self.assertEqual(p._account_cache(0)["packs"][0]["name"], "SevenTV_a")
        for index, path in enumerate(("one.png", "two.png", "three.png")):
            p._on_upload_event(1, 0, [path, object()])
            self.respond_media(1001 + index)
            request, _account = self.respond_set(5001 + index, "SevenTV_a", reverse=True)
            self.assertIsInstance(request, TL.TL_stickers_addStickerToSet)
        self.assertEqual(len(self.server_sets), 3)
        self.assertEqual(len(self.server_sets["SevenTV_a"]), 4)
        self.assertEqual(len(self.server_sets["SevenTV_b"]), 1)
        self.assertEqual(len(sent), 1)

    def test_failed_owned_pack_lookup_does_not_create_another_pack(self):
        p = self.plugin
        p._account_cache(0).pop("packs_checked")
        p._prepare_tiles = lambda _emote: ["one.png"]
        _state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        _request, callback, _account = self.requests.pop(0)
        callback(None, NS(text="NETWORK_ERROR"))
        self.assertEqual(self.requests, [])
        self.assertEqual(self.uploads, [])
        self.assertEqual(sent, [])
        self.assertEqual(p._account_cache(0)["packs"], [])

    def test_empty_owned_pack_lookup_allows_first_pack_creation(self):
        p = self.plugin
        p._account_cache(0).pop("packs_checked")
        p._prepare_tiles = lambda _emote: ["one.png"]
        _state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        _request, callback, _account = self.requests.pop(0)
        response = TL.TL_messages_myStickers()
        response.sets = JList()
        callback(response, None)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1001)
        request, _account = self.respond_set(5001)
        self.assertIsInstance(request, TL.TL_stickers_createStickerSet)
        self.assertEqual(len(sent), 1)

    def test_unrecognized_creation_response_saves_pack_before_retry(self):
        p = self.plugin
        p._prepare_tiles = lambda _emote: ["one.png"]
        _state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1001)
        _request, callback, _account = self.requests.pop(0)
        callback(self.set_response("my_pack", []), None)
        request, callback, _account = self.requests.pop(0)
        self.assertIsInstance(request, TL.TL_messages_getStickerSet)
        callback(self.set_response("my_pack", []), None)
        saved = json.loads(p._cache_path.read_text())
        self.assertEqual(saved["100"]["packs"][0]["name"], "my_pack")
        self.assertEqual(sent, [])
        # Even an unrecognized response cannot lead to another create request.
        p._defer_send(view, (), False)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1002)
        request, _account = self.respond_set(5001)
        self.assertIsInstance(request, TL.TL_stickers_addStickerToSet)
        self.assertEqual(len(sent), 1)

    def test_ambiguous_added_documents_never_choose_arbitrary_last_emoji(self):
        p = self.plugin
        p._account_cache(0)["packs"].append({"name": "my_pack", "count": 1})
        self.server_sets["my_pack"] = [self.emoji_document(4001)]
        p._prepare_tiles = lambda _emote: ["one.png"]
        _state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1001)
        _request, callback, _account = self.requests.pop(0)
        callback(self.set_response("my_pack", [self.emoji_document(i) for i in (4001, 5001, 5002)]), None)
        request, callback, _account = self.requests.pop(0)
        self.assertIsInstance(request, TL.TL_messages_getStickerSet)
        callback(self.set_response("my_pack", [self.emoji_document(i) for i in (4001, 5001, 5002)]), None)
        self.assertIsNone(p._cached_tiles(0, "01ABC"))
        self.assertEqual(sent, [])
        self.assertEqual(p._account_cache(0)["packs"][0]["count"], 3)
        self.assertIn("returned_ids=[4001, 5001, 5002]", self.logs[-1])

    def test_short_name_collision_retries_same_document_with_bounded_new_names(self):
        p = self.plugin
        p._prepare_tiles = lambda _emote: ["one.png"]
        state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1001)
        names = []
        for _attempt in range(3):
            request, callback, _account = self.requests.pop(0)
            names.append(request.short_name)
            self.assertEqual(request.stickers.get(0).document.id, 1001)
            callback(None, NS(text="PACK_SHORT_NAME_OCCUPIED"))
        self.assertEqual(len(set(names)), 3)
        self.assertEqual(len(self.uploads), 1)
        self.assertEqual(self.requests, [])
        self.assertEqual(sent, [])
        self.assertEqual(state["text"], "Wide")

        self.assertEqual(p._account_cache(0)["packs"], [])

    def begin_document_resolution(self, existing=None):
        p = self.plugin
        if existing is not None:
            p._account_cache(0)["packs"].append({"name": "my_pack", "count": len(existing)})
            self.server_sets["my_pack"] = existing
        p._prepare_tiles = lambda _emote: ["one.png"]
        _state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1001)
        request, callback, _account = self.requests.pop(0)
        return request, callback, sent

    def marked_document_response(self, ids, marked_id):
        response = self.set_response("my_pack", [self.emoji_document(i) for i in ids])
        marker = self.plugin._tile_keyword(self.plugin._active[0])
        response.keywords = JList([NS(document_id=marked_id, keyword=JList([marker]))])
        return response

    def test_document_resolution_single_new_document_without_custom_attribute(self):
        _request, callback, sent = self.begin_document_resolution()
        attr = TL.TL_documentAttributeSticker()
        attr.alt = "🙂"
        callback(self.set_response("my_pack", [NS(id=5001, attributes=JList([attr]))]), None)
        self.assertEqual(self.plugin._cached_tiles(0, "01ABC"), [(5001, "🙂")])
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.requests, [])

    def test_document_resolution_empty_alt_is_not_an_identity_failure(self):
        _request, callback, sent = self.begin_document_resolution()
        doc = self.emoji_document(5001)
        doc.attributes.get(0).alt = ""
        callback(self.set_response("my_pack", [doc]), None)
        self.assertEqual(self.plugin._cached_tiles(0, "01ABC"), [(5001, "🙂")])
        self.assertEqual(len(sent), 1)

    def test_document_resolution_marks_upload_and_resolves_existing_server_id(self):
        request, callback, sent = self.begin_document_resolution([self.emoji_document(4001)])
        self.assertEqual(request.sticker.flags & 2, 2)
        self.assertEqual(request.sticker.keywords, self.plugin._tile_keyword(self.plugin._active[0]))
        callback(self.marked_document_response([4001], 4001), None)
        self.assertEqual(self.plugin._cached_tiles(0, "01ABC"), [(4001, "🙂")])
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.requests, [])

    def test_document_resolution_marker_disambiguates_concurrent_pack_changes(self):
        _request, callback, sent = self.begin_document_resolution([self.emoji_document(4001)])
        callback(self.marked_document_response([5002, 4001, 5001], 5001), None)
        self.assertEqual(self.plugin._cached_tiles(0, "01ABC"), [(5001, "🙂")])
        self.assertEqual(len(sent), 1)

    def test_document_resolution_refetches_empty_response_without_another_add(self):
        _request, callback, sent = self.begin_document_resolution()
        callback(self.set_response("my_pack", []), None)
        request, callback, _account = self.requests.pop(0)
        self.assertIsInstance(request, TL.TL_messages_getStickerSet)
        self.assertEqual(request.hash, 0)
        callback(self.set_response("my_pack", [self.emoji_document(5001)]), None)
        self.assertEqual(self.plugin._cached_tiles(0, "01ABC"), [(5001, "🙂")])
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(self.uploads), 1)
        self.assertEqual(self.requests, [])

    def test_document_resolution_never_selects_unrelated_single_old_document(self):
        old = self.emoji_document(4001)
        _request, callback, sent = self.begin_document_resolution([old])
        callback(self.set_response("my_pack", [old]), None)
        request, callback, _account = self.requests.pop(0)
        self.assertIsInstance(request, TL.TL_messages_getStickerSet)
        callback(self.set_response("my_pack", [old]), None)
        self.assertIsNone(self.plugin._cached_tiles(0, "01ABC"))
        self.assertEqual(sent, [])
        self.assertEqual(self.requests, [])
        self.assertEqual(len(self.uploads), 1)
        self.assertEqual(len(self.plugin._account_cache(0)["packs"]), 1)

    def test_document_resolution_recovers_marked_tile_before_readding(self):
        p = self.plugin
        p._account_cache(0)["packs"].append({"name": "my_pack", "count": 1})
        p._prepare_tiles = lambda _emote: ["one.png"]
        _state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1001, snapshot=False)
        request, callback, _account = self.requests.pop(0)
        self.assertIsInstance(request, TL.TL_messages_getStickerSet)
        callback(self.marked_document_response([4001], 4001), None)
        self.assertEqual(p._cached_tiles(0, "01ABC"), [(4001, "🙂")])
        self.assertEqual(self.requests, [])
        self.assertEqual(len(sent), 1)

    def test_document_resolution_refetch_failure_preserves_pack_and_draft(self):
        _request, callback, sent = self.begin_document_resolution()
        callback(self.set_response("my_pack", []), None)
        _request, callback, _account = self.requests.pop(0)
        callback(None, NS(text="NETWORK_ERROR"))
        self.assertEqual(sent, [])
        self.assertIsNone(self.plugin._cached_tiles(0, "01ABC"))
        self.assertEqual(self.plugin._account_cache(0)["packs"][0]["name"], "my_pack")
        self.assertEqual(self.requests, [])

    def test_document_resolution_rejects_non_emoji_pack(self):
        _request, callback, sent = self.begin_document_resolution()
        response = self.set_response("my_pack", [self.emoji_document(5001)])
        response.set.emojis = False
        callback(response, None)
        self.assertIsNone(self.plugin._cached_tiles(0, "01ABC"))
        self.assertEqual(sent, [])

    def test_document_resolution_marker_uses_emote_id_and_tile_not_alias(self):
        p = self.plugin
        job = {"emote": self.emote, "index": 0}
        marker = p._tile_keyword(job)
        self.emote.code = "AnotherAlias"
        self.assertEqual(p._tile_keyword(job), marker)
        job["index"] = 1
        self.assertNotEqual(p._tile_keyword(job), marker)
        job["index"] = 0
        self.emote.emote_id = "02DEF"
        self.assertNotEqual(p._tile_keyword(job), marker)

    @staticmethod
    def twitch_item(code="Kappa", emote_id="25", animated=False):
        return {"code": code, "provider": 0, "animated": animated, "urls": [{
            "size": "1x", "url": f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}/default/light/1.0",
        }]}

    def test_twitch_native_static_global_and_animated_channel(self):
        global_emote = ENV["_parse_twitch_emotes"]([self.twitch_item()])[0]
        self.assertEqual(global_emote.code, "Kappa")
        self.assertEqual(global_emote.emote_id, "twitch_25")
        self.assertEqual(global_emote.channel, ENV["_TWITCH_GLOBAL"])
        self.assertIsNone(global_emote.animation_url)
        self.assertTrue(global_emote.source_url.endswith("/static/dark/2.0"))
        item = self.twitch_item("t2xSpin", "emotesv2_abc", True)
        channel_emote = ENV["_parse_twitch_emotes"]([item], "t2x2")[0]
        self.assertEqual(channel_emote.provider, "Twitch")
        self.assertEqual(channel_emote.channel, "t2x2")
        self.assertTrue(channel_emote.animation_url.endswith("/animated/dark/2.0"))
        self.assertTrue(channel_emote.preview_animation_url.endswith("/animated/dark/1.0"))

    def test_twitch_native_rejects_untrusted_cdn_and_invalid_ids(self):
        parse = ENV["_parse_twitch_emotes"]
        for url in ("https://static-cdn.jtvnw.net.evil/emoticons/v2/25/default/light/1.0",
                    "http://static-cdn.jtvnw.net/emoticons/v2/25/default/light/1.0",
                    "https://static-cdn.jtvnw.net/emoticons/v2/../../default/light/1.0"):
            item = self.twitch_item()
            item["urls"][0]["url"] = url
            with self.assertRaises(ValueError):
                parse([item])
        self.assertEqual(parse([]), [])

    def test_twitch_native_namespace_and_alias_collisions_remain_separate(self):
        twitch = ENV["_parse_twitch_emotes"]([self.twitch_item("Wide", "01ABC")], "t2x2")[0]
        self.assertNotEqual(twitch.emote_id, self.emote.emote_id)
        items = ENV["_picker_items"]({"seven": self.emote, "native": twitch}, "Wide", "t2x2")
        self.assertEqual(len(items), 2)
        self.assertEqual(ENV["_picker_items"]({"seven": self.emote, "native": twitch}, "Twitch"), [twitch])
        self.assertNotEqual(ENV["_emote_source"](twitch), ENV["_emote_source"](self.emote))

    def test_twitch_native_download_accepts_only_emote_cdn_paths(self):
        emote = ENV["_parse_twitch_emotes"]([self.twitch_item()])[0]
        path = self.plugin._storage / "native.png"
        with patch.dict(ENV, {"urlopen": lambda *_args, **_kwargs: io.BytesIO(b'png-data')}):
            self.plugin._download(emote.source_url, path)
            self.assertEqual(path.read_bytes(), b'png-data')
            for url in ("https://static-cdn.jtvnw.net/not-an-emote", "https://example.com/emoticons/v2/25"):
                with self.assertRaises(ValueError):
                    self.plugin._download(url, path)

    def test_twitch_native_catalogue_cache_survives_network_failure(self):
        raw = json.dumps([self.twitch_item()]).encode()
        with patch.dict(ENV, {"urlopen": lambda *_args, **_kwargs: io.BytesIO(raw)}):
            first = self.plugin._fetch_twitch_emotes()
        def unavailable(*_args, **_kwargs):
            raise OSError("offline")
        with patch.dict(ENV, {"urlopen": unavailable}):
            cached = self.plugin._fetch_twitch_emotes()
        self.assertEqual(first[0].emote_id, cached[0].emote_id)
        self.assertIn("using cache", self.logs[-1])
        self.assertTrue((self.plugin._storage / "twitch_catalog_global.json").exists())

    def test_twitch_native_bad_catalogue_does_not_replace_cache(self):
        path = self.plugin._storage / "twitch_catalog_channel_t2x2.json"
        path.write_text(json.dumps([self.twitch_item()]))
        with patch.dict(ENV, {"urlopen": lambda *_args, **_kwargs: io.BytesIO(b'{"error":"bad response"}')}):
            cached = self.plugin._fetch_twitch_emotes("t2x2")
        self.assertEqual(cached[0].code, "Kappa")
        self.assertIsInstance(json.loads(path.read_text()), list)

    def test_twitch_native_channel_loads_without_seventv_account(self):
        p = self.plugin
        p._fetch_twitch_emotes = lambda channel=None: ENV["_parse_twitch_emotes"]([
            self.twitch_item("t2xLUV" if channel else "Kappa")], channel)
        p._gql = lambda *_args: {"users": {"search": {"items": []}}}
        finished = []
        p._finish_channels = lambda *args: finished.append(args)
        p._fetch_channels(1, ["t2x2"])
        emotes = list(finished[0][1].values())
        self.assertEqual({emote.code for emote in emotes}, {"Kappa", "t2xLUV"})

    def test_twitch_native_empty_channel_setting_still_loads_globals(self):
        p = self.plugin
        p._channels_text = ""
        calls = []
        p._fetch_channels = lambda generation, names: calls.append((generation, names))
        with patch.dict(ENV, {"PLUGINS_QUEUE": object(), "run_on_queue": lambda callback, *_args: callback()}):
            p._reload_channels()
        self.assertEqual(calls, [(2, [])])

    def test_twitch_native_failure_does_not_block_seventv(self):
        p = self.plugin
        def unavailable(_channel=None):
            raise OSError("Twitch unavailable")
        p._fetch_twitch_emotes = unavailable
        def gql(query, _variables):
            if query == ENV["_USER_QUERY"]:
                return {"users": {"search": {"items": [{"connections": [{
                    "platform": "TWITCH", "platformUsername": "t2x2",
                }], "style": {"activeEmoteSet": {"id": "set"}}}]}}}
            return {"emoteSets": {"emoteSet": {"emotes": {"pageCount": 1, "items": [{
                "alias": "Wide", "emote": {"id": "01ABC", "images": [{
                    "mime": "image/png", "frameCount": 1, "width": 96, "height": 96,
                    "scale": 1, "url": "https://cdn.7tv.app/emote/01ABC/1x.png",
                }]},
            }]}}}}
        p._gql = gql
        finished = []
        p._finish_channels = lambda *args: finished.append(args)
        p._fetch_channels(1, ["t2x2"])
        self.assertEqual([emote.code for emote in finished[0][1].values()], ["Wide"])
        self.assertTrue(finished[0][2])

    def test_pack_title_rejection_preserves_draft_and_logs_request_names(self):
        p = self.plugin
        p._prepare_tiles = lambda _emote: ["one.png"]
        state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1001)
        request, callback, _account = self.requests.pop(0)
        callback(None, NS(text="PACK_TITLE_INVALID"))
        self.assertEqual(state["text"], "Wide")
        self.assertEqual(sent, [])
        self.assertEqual(p._account_cache(0)["packs"], [])
        self.assertEqual(self.requests, [])
        self.assertIn("PACK_TITLE_INVALID", self.logs[-1])
        self.assertIn(request.title, self.logs[-1])
        self.assertIn(request.short_name, self.logs[-1])

    def test_changed_context_or_draft_cancels_automatic_send(self):
        for change in ("text", "reply", "edit", "dialog", "shown", "revision", "account"):
            with self.subTest(change=change):
                p = self.plugin
                callbacks = []
                p._ensure_uploaded = lambda _account, _emote, callback: callbacks.append(callback)
                state, view, watcher, sent = self.composer()
                self.users[0] = 100
                p._defer_send(view, (), False)
                if change == "revision":
                    watcher.revision += 1
                elif change == "account":
                    self.users[0] = 999
                else:
                    state[change] = {"text": "changed", "reply": object(), "edit": object(),
                                     "dialog": 11, "shown": False}[change]
                callbacks[0](None)
                self.assertEqual(sent, [])

    def test_upload_timeout_preserves_message_and_drops_late_result(self):
        p = self.plugin
        p._prepare_tiles = lambda _emote: ["one.png"]
        state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        self.delayed[0]()
        p._on_upload_event(1, 0, ["one.png", object()])
        self.assertEqual(self.requests, [])
        self.assertEqual(sent, [])
        self.assertEqual(state["text"], "Wide")
        self.assertEqual(len(self.errors), 1)

    def test_deleted_pack_retries_in_new_pack(self):
        p = self.plugin
        p._account_cache(0)["packs"].append({"name": "deleted", "count": 5})
        p._prepare_tiles = lambda _emote: ["one.png"]
        _state, view, _watcher, sent = self.composer()
        p._defer_send(view, (), False)
        p._on_upload_event(1, 0, ["one.png", object()])
        self.respond_media(1001)
        request, callback, _account = self.requests.pop(0)
        self.assertIsInstance(request, TL.TL_stickers_addStickerToSet)
        callback(None, NS(text="STICKERSET_INVALID"))
        create, _account = self.respond_set(1001, "new_pack")
        self.assertIsInstance(create, TL.TL_stickers_createStickerSet)
        self.assertEqual(len(sent), 1)

    def test_account_slot_reuse_does_not_reuse_another_users_cache(self):
        self.plugin._account_cache(0)["emotes"]["01ABC"] = [{"id": 1, "alt": "🙂"}]
        self.users[0] = 200
        self.assertIsNone(self.plugin._cached_tiles(0, "01ABC"))

    def test_conversion_uses_utf16_removes_only_owned_visuals_preserves_formatting(self):
        p = self.plugin
        p._account_cache(0)["emotes"]["01ABC"] = [{"id": 11, "alt": "🙂"}, {"id": 12, "alt": "🙂"}]
        text = RichText("😀 Wide Wide 🙂")
        for first, last in ((3, 7), (8, 12)):
            marker, visual = Annotation(), ReplacementSpan()
            text.setSpan(marker, first, last, 33)
            text.setSpan(visual, first, last, 33)
            p._markers[id(marker)] = self.emote
            p._visuals[id(visual)] = visual
        bold, native = object(), EmojiSpan(77, None)
        text.setSpan(bold, 3, 12, 33)
        text.setSpan(native, 13, 15, 33)
        result = p._convert_entities(text, 0)
        self.assertEqual(str(result), "😀 🙂🙂 🙂🙂 🙂")
        self.assertEqual([(span.document_id, first, last) for span, first, last in result.spans
                          if isinstance(span, EmojiSpan)], [(77, 13, 15), (11, 8, 10), (12, 10, 12), (11, 3, 5), (12, 5, 7)])
        self.assertEqual(result.getSpanStart(bold), 3)
        self.assertEqual(result.getSpanEnd(bold), 12)
        self.assertFalse(any(id(span) in p._visuals for span, _first, _last in result.spans))
        self.assertEqual(str(text), "😀 Wide Wide 🙂")

    def test_native_pixel_tiles_reconstruct_wide_tall_and_small_sources(self):
        for width, height in ((260, 96), (217, 215), (33, 49), (2101, 1)):
            with self.subTest(width=width, height=height):
                pixels = [[1 + row * width + col for col in range(width)] for row in range(height)]
                emote = Emote("channel", "Code", f"id{width}", "unused", "unused")
                (self.plugin._storage / f"source_{emote.emote_id}.png").touch()
                with patch.dict(ENV, {"BitmapFactory": NS(decodeFile=lambda _path: Bitmap(copy.deepcopy(pixels)))}):
                    paths = self.plugin._prepare_tiles(emote)
                origins = ENV["_tile_origins"](width, height)
                self.assertEqual(len(paths), len(origins))
                for path, (left, top) in zip(paths, origins):
                    tile = json.loads(Path(path).read_text())
                    self.assertEqual((len(tile), len(tile[0])), (100, 100))
                    offset_x = (100 - width) // 2 if width < 100 else 0
                    offset_y = (100 - height) // 2 if height < 100 else 0
                    for row in range(min(100, height - top)):
                        for col in range(min(100, width - left)):
                            self.assertEqual(tile[row + offset_y][col + offset_x], pixels[row + top][col + left])

    def test_failed_png_export_leaves_no_partial_cached_tile(self):
        (self.plugin._storage / "source_01ABC.png").touch()
        with patch.dict(ENV, {"BitmapFactory": NS(decodeFile=lambda _path: Bitmap([[1]]))}), patch.object(Bitmap, "fail_compress", True):
            with self.assertRaisesRegex(ValueError, "PNG export"):
                self.plugin._prepare_tiles(self.emote)
        self.assertEqual([path.name for path in self.plugin._storage.iterdir()], ["source_01ABC.png"])

    def animated_environment(self, fail_frame=False, output_sizes=(4,)):
        """Exercise the conversion workflow, stubbing only Android/JNI boundaries."""
        times, frames, encoders, stops = [], [], [], []
        movie = NS(width=lambda: 150, height=lambda: 1, duration=lambda: 5000,
                   setTime=times.append,
                   draw=lambda canvas, x, y: canvas.drawBitmap(Bitmap([list(range(1, 151))]), x, y, None))

        def create_encoder(path, width, height, fps, bitrate):
            encoders.append((path, width, height, fps, bitrate))
            return len(encoders)

        def write_frame(pointer, buffer, width, height):
            frames.append((pointer, list(buffer.bitmap.pixels[49]), width, height))
            return not fail_frame

        def stop(pointer):
            stops.append(pointer)
            size = output_sizes[min(pointer - 1, len(output_sizes) - 1)]
            Path(encoders[pointer - 1][0]).write_bytes(b"w" * size)

        buffer = NS(clear=lambda: None, flip=lambda: None)
        encoder = NS(createEncoder=create_encoder, writeFrame=write_frame, stop=stop)
        patches = {
            "Movie": NS(decodeFile=lambda _path: movie),
            "jclass": lambda _name: NS(JA=encoder),
            "ByteBuffer": NS(allocateDirect=lambda _size: buffer),
        }
        self.enterContext(patch.dict(ENV, patches))
        self.enterContext(patch.object(Bitmap, "getByteCount", lambda _bitmap: 40000, create=True))
        self.enterContext(patch.object(Bitmap, "eraseColor", lambda bitmap, _color: setattr(bitmap, "pixels", [[0] * 100 for _ in range(100)]), create=True))
        self.enterContext(patch.object(Bitmap, "copyPixelsToBuffer", lambda bitmap, target: setattr(target, "bitmap", bitmap), create=True))
        (self.plugin._storage / "source_01ABC.gif").touch()
        self.emote.animation_url = "unused"
        return times, frames, encoders, stops

    def test_animation_samples_full_loop_and_crops_native_pixels(self):
        times, frames, encoders, stops = self.animated_environment()
        paths = self.plugin._prepare_tiles(self.emote)
        self.assertEqual(len(paths), 2)
        self.assertEqual(len(frames), 180)
        self.assertEqual((times[0], times[89], times[90]), (0, 4944, 0))
        self.assertTrue(all(entry[1:4] == (100, 100, 30) for entry in encoders))
        self.assertEqual(frames[0][1], list(range(1, 101)))
        self.assertEqual(frames[90][1], list(range(101, 151)) + [0] * 50)
        self.assertEqual(stops, [1, 2])

    def test_failed_animation_leaves_no_partial_webm(self):
        _times, _frames, _encoders, stops = self.animated_environment(fail_frame=True)
        with self.assertRaisesRegex(RuntimeError, "WebM frame"):
            self.plugin._prepare_tiles(self.emote)
        self.assertEqual(stops, [1])
        self.assertEqual([path.name for path in self.plugin._storage.iterdir()], ["source_01ABC.gif"])

    def test_animation_retries_bitrate_when_file_is_too_large(self):
        _times, _frames, encoders, _stops = self.animated_environment(output_sizes=(300000, 4))
        self.plugin._prepare_tiles(self.emote)
        self.assertEqual([entry[4] for entry in encoders], [128000, 64000, 128000])
        self.assertFalse(any(path.name.startswith("tmp") for path in self.plugin._storage.iterdir()))


if __name__ == "__main__":
    unittest.main()
