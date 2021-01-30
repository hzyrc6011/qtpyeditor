# -*- coding:utf-8 -*-
# @Time: 2021/1/18 9:26
# @Author: Zhanyi Hou
# @Email: 1295752786@qq.com
# @File: basecodeedit.py
import os
import re
import time
from itertools import groupby
from queue import Queue

from qtpy.QtWidgets import QAction
from qtpy.QtCore import QRegExp, Qt, QModelIndex, Signal, QThread, QCoreApplication, QTimer
from qtpy.QtWidgets import QApplication, QFileDialog, QTextEdit, QTabWidget, \
    QMessageBox, QListWidget, QListWidgetItem, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPlainTextEdit, QShortcut
from qtpy.QtGui import QTextCursor, QKeyEvent, QMouseEvent, QIcon, QKeySequence, QFocusEvent, QColor, QTextFormat, \
    QPainter, QTextDocument, QTextBlock
from typing import List, Tuple, Dict

from qtpyeditor.highlighters.python import PythonHighlighter
from qtpyeditor.syntaxana import getIndent

from qtpyeditor.linenumber import QCodeEditor


class AutoCompList(QListWidget):
    def __init__(self, parent: 'PMBaseCodeEdit' = None):
        super().__init__(parent)
        self._parent: 'PMBaseCodeEdit' = parent
        self.autocomp_list: List[str] = []
        self.last_show_time = 0

    def can_show(self):
        if time.time() - self.last_show_time < 1:
            return False
        return True

    def show(self) -> None:
        self.last_show_time = time.time()
        super().show()

    def hide_autocomp(self):
        self.autocomp_list = []
        self.hide()
        self._parent.setFocus()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if self.isVisible():
            if e.key() == Qt.Key_Return or e.key() == Qt.Key_Tab:
                self._parent._insert_autocomp()
                self._parent.setFocus()
                e.accept()
                return
            elif e.key() == Qt.Key_Escape:
                self.hide()
                self._parent.setFocus()
                return
            elif e.key() == Qt.Key_Up or e.key() == Qt.Key_Down:
                super().keyPressEvent(e)
                e.accept()
                return
            elif e.key() == Qt.Key_Left or e.key() == Qt.Key_Right:
                self.hide_autocomp()
            else:
                self.hide_autocomp()
        super().keyPressEvent(e)
        e.ignore()


class PMBaseCodeEdit(QCodeEditor):
    # cursorPositionChanged = Signal()
    signal_save = Signal()
    signal_focused_in = Signal(QFocusEvent)
    signal_idle = Signal()

    UPDATE_CODE_HIGHLIGHT = 1

    def __init__(self, parent=None):
        super(PMBaseCodeEdit, self).__init__(parent)
        self._last_operation: float = 0.0  # 记录上次操作的时间
        self.update_request_queue = Queue()

        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.doc_tab_widget: 'PMGPythonEditor' = parent
        self.filename = '*'
        self.path = ''
        self.modified = True
        self.highlighter: 'PythonHighlighter' = None
        self.setTabChangesFocus(False)

        self.textChanged.connect(self.on_text_changed)

        self.popup_hint_widget = AutoCompList(self)
        self.popup_hint_widget.doubleClicked.connect(self._insert_autocomp)
        self.popup_hint_widget.hide()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui_update_timer = QTimer()
        self.ui_update_timer.start(300)

        self.ui_update_timer.timeout.connect(self.update_ui)

        self.textChanged.connect(self.update_last_operation_time)

    def update_last_operation_time(self):
        """
        更新上一次操作的时间
        :return:
        """
        self._last_operation = time.time()

    def update_ui(self):
        if not self.isVisible():
            return
        if time.time() - self._last_operation > 0.5:
            if self.update_request_queue.qsize() > 0:

                action: int = self.update_request_queue.get()
                if action == self.UPDATE_CODE_HIGHLIGHT:
                    self.highlighter.rehighlight()

    def focusInEvent(self, event: 'QFocusEvent') -> None:
        self.signal_focused_in.emit(event)
        super().focusInEvent(event)

    def on_autocomp_signal_received(self, text_cursor_pos: tuple, completions: List['jedi.api.classes.Completion']):
        '''
        当收到自动补全提示信号时，执行的函数。
        :param text_cursor_pos:
        :param completions:
        :return:
        '''
        current_cursor_pos = self._get_textcursor_pos()
        if current_cursor_pos[0] + 1 == text_cursor_pos[0] and current_cursor_pos[1] == text_cursor_pos[1]:
            if len(completions) == 1:
                if completions[0].name == self._get_hint():
                    self.hide_autocomp()
                    return

            self.autocomp_show(completions)
        else:
            self.hide_autocomp()

    def hide_autocomp(self):
        self.popup_hint_widget.hide_autocomp()

    def on_text_changed(self):
        self._get_textcursor_pos()
        cursor_pos = self.cursorRect()
        self.popup_hint_widget.setGeometry(
            cursor_pos.x() + 5, cursor_pos.y() + 20, 150, 200)
        self._request_autocomp()
        if self.modified == True:
            return
        else:
            self.modified = True
            self.updateUi()

    def _insert_autocomp(self, e: QModelIndex = None):
        row = self.popup_hint_widget.currentRow()
        if 0 <= row < len(self.popup_hint_widget.autocomp_list):
            # if self._get_nearby_text()[-1] in '+-*/\\=\'\"[]\{\}(), '
            self.insertPlainText(self.popup_hint_widget.autocomp_list[row])
            textcursor: QTextCursor = self.textCursor()
            word = self.get_word(textcursor.blockNumber(), textcursor.columnNumber())
            print('word',word)
            if word in self.highlighter.KEYWORDS:
                self.insertPlainText(' ')
            self.popup_hint_widget.hide()

    def _get_nearby_text(self):
        block_text = self.textCursor().block().text()
        col = self.textCursor().columnNumber()
        return block_text[:col]

    def _get_hint(self):
        block_text = self.textCursor().block().text()
        if block_text.lstrip().startswith('#'):  # 在注释中
            return ''
        col = self.textCursor().columnNumber()
        nearby_text = block_text[:col]
        hint = re.split(
            '[.:;,?!\s \+ \- = \* \\ \/  \( \)\[\]\{\} ]', nearby_text)[-1]
        return hint

    def _request_autocomp(self):
        pos = self._get_textcursor_pos()
        nearby_text = self._get_nearby_text()
        hint = self._get_hint()

        if hint == '' and not nearby_text.endswith(('.', '\\\\', '/')):
            self.popup_hint_widget.hide_autocomp()
            return
        self.autocomp_thread.text_cursor_pos = (pos[0] + 1, pos[1])
        self.autocomp_thread.text = self.toPlainText()

    def autocomp_show(self, completions: list):
        self.popup_hint_widget.clear()
        l = []
        if len(completions) != 0:
            for completion in completions:
                l.append(completion.complete)
                self.popup_hint_widget.addItem(
                    QListWidgetItem(completion.name))
            self.popup_hint_widget.show()
            self.popup_hint_widget.setFocus()
            self.popup_hint_widget.setCurrentRow(0)
        else:
            self.popup_hint_widget.hide()
        self.popup_hint_widget.autocomp_list = l

    def _get_textcursor_pos(self) -> Tuple[int, int]:
        return self.textCursor().blockNumber(), self.textCursor().columnNumber()

    def updateUi(self):
        if self.modified:
            text = ''  # '未保存'
        else:
            text = ''  # '已保存'
        self.doc_tab_widget.modified_status_label.setText(text)

    def mousePressEvent(self, a0: QMouseEvent) -> None:
        if self.popup_hint_widget.isVisible():
            self.popup_hint_widget.hide_autocomp()
        super().mousePressEvent(a0)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        k = event.key()
        if k == Qt.Key_Tab:
            self.on_tab()
            return
        elif k == Qt.Key_Backtab:
            self.on_back_tab()
            return
        elif k == Qt.Key_S and event.modifiers() == Qt.ControlModifier:
            self.save()
            return
        elif k == Qt.Key_Slash and event.modifiers() == Qt.ControlModifier:
            self.comment()
        elif k == Qt.Key_Return:
            if not self.textCursor().atBlockEnd():
                pass
            else:
                self.on_return_pressed()
                event.accept()
                return
        elif k == Qt.Key_Backspace:
            self.on_backspace(event)
            event.accept()
            return
        elif k == Qt.Key_ParenLeft:
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.insertText('()')
            cursor.movePosition(QTextCursor.PreviousCharacter, QTextCursor.MoveAnchor, 1)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            event.accept()
            return
        elif k == Qt.Key_BracketLeft:
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.insertText('[]')
            cursor.movePosition(QTextCursor.PreviousCharacter, QTextCursor.MoveAnchor, 1)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            event.accept()
            return
        elif k == Qt.Key_BraceLeft:
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.insertText('{}')
            cursor.movePosition(QTextCursor.PreviousCharacter, QTextCursor.MoveAnchor, 1)
            cursor.endEditBlock()
            self.setTextCursor(cursor)

            event.accept()
            return
        super().keyPressEvent(event)

    def on_backspace(self, key_backspace_event: QKeyEvent):
        cursor: QTextCursor = self.textCursor()
        cursor.beginEditBlock()
        text = cursor.block().text()
        nearby_text = self._get_nearby_text()
        move_left = (cursor.columnNumber()) % 4
        if move_left == 0:
            move_left = 4
        if nearby_text.isspace():
            for i in range(move_left):
                cursor.deletePreviousChar()

        else:
            super().keyPressEvent(key_backspace_event)
        cursor.endEditBlock()

    def on_return_pressed(self):
        '''
        按回车换行的方法
        :return:
        '''
        cursor = self.textCursor()
        cursor.beginEditBlock()
        text = cursor.block().text()
        text, indent = getIndent(text)

        if text.endswith(':'):

            cursor.insertText('\n' + ' ' * (indent + 4))
        else:

            cursor.insertText('\n' + ' ' * indent)
        cursor.endEditBlock()

    def comment(self):
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            start = cursor.anchor()
            end = cursor.position()

            if start > end:
                start, end = end, start

            cursor.clearSelection()

            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.StartOfLine)
            start_line = cursor.blockNumber()

            start = cursor.position()  # 将光标移动到行首，获取行首的位置
            cursor.setPosition(end)  # 将光标设置到末尾
            cursor.movePosition(QTextCursor.StartOfLine)  # 将光标设置到选区最后一行
            end_line = cursor.blockNumber()  # 获取光标的行号

            cursor.setPosition(start)
            current_line = cursor.blockNumber()
            last_line = current_line
            print(start_line, end_line, current_line)
            while current_line <= end_line:
                line_text, indent = getIndent(cursor.block().text())
                print(current_line, line_text, indent)
                if line_text.startswith('#'):
                    cursor.movePosition(
                        QTextCursor.NextCharacter, QTextCursor.MoveAnchor, indent)
                    cursor.deleteChar()
                else:
                    cursor.insertText('#')
                cursor.movePosition(QTextCursor.StartOfLine)
                cursor.movePosition(QTextCursor.Down)
                current_line = cursor.blockNumber()
                if current_line == last_line:
                    break
                last_line = current_line

            cursor.movePosition(QTextCursor.StartOfLine)
        else:
            print('comment!')
            cursor.movePosition(QTextCursor.StartOfLine)
            line_text, indent = getIndent(cursor.block().text())
            if line_text.startswith('#'):
                cursor.movePosition(QTextCursor.NextCharacter,
                                    QTextCursor.MoveAnchor, indent)
                cursor.deleteChar()
            else:
                cursor.insertText('#')
            pass

        cursor.endEditBlock()

    def on_back_tab(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            self.editUnindent()

        else:
            cursor = self.textCursor()
            cursor.clearSelection()

            cursor.movePosition(QTextCursor.StartOfBlock)

            for i in range(4):
                cursor.movePosition(QTextCursor.NextCharacter,
                                    QTextCursor.KeepAnchor, 1)
                if not cursor.selectedText().endswith(' '):
                    cursor.movePosition(QTextCursor.PreviousCharacter,
                                        QTextCursor.KeepAnchor, 1)
                    break
            # print('cursor.selected',cursor.selectedText())
            cursor.removeSelectedText()

    def on_tab(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            self.editIndent()
            return
        else:
            nearby_text = self._get_nearby_text()
            hint = self._get_hint()

            if hint == '' and not nearby_text.endswith(('.', '\\\\', '/')):
                cursor = self.textCursor()
                cursor.insertText("    ")
            else:
                self._request_autocomp()

    def editIndent(self):
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            start = pos = cursor.anchor()
            start_line = self.document().findBlock(start)
            end = cursor.position()

            if start > end:
                start, end = end, start
                pos = start
            cursor.clearSelection()

            cursor.setPosition(end)
            cursor.movePosition(QTextCursor.StartOfLine)
            end = cursor.position()
            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.StartOfLine)
            start = cursor.position()

            cursor.setPosition(end)
            while pos >= start:
                cursor.insertText("    ")

                cursor.movePosition(QTextCursor.Up)
                cursor.movePosition(QTextCursor.StartOfLine)
                lastPos = pos
                pos = cursor.position()
                if lastPos == pos:
                    break

                print('end loop', pos, start)
            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.NextCharacter,
                                QTextCursor.KeepAnchor, end - start)
        cursor.endEditBlock()
        return True

    def editUnindent(self):
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            start = pos = cursor.anchor()
            end = cursor.position()
            if start > end:
                start, end = end, start
                pos = start
            cursor.clearSelection()
            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.StartOfLine)
            start = cursor.position()
            cursor.setPosition(end)
            cursor.movePosition(QTextCursor.StartOfLine)
            end = cursor.position()
            while pos >= start:
                cursor.movePosition(QTextCursor.NextCharacter,
                                    QTextCursor.KeepAnchor, 4)
                if cursor.selectedText() == "    ":
                    cursor.removeSelectedText()
                cursor.movePosition(QTextCursor.Up)
                cursor.movePosition(QTextCursor.StartOfLine)
                lastpos = pos
                pos = cursor.position()
                if pos == lastpos:
                    break
            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.NextCharacter,
                                QTextCursor.KeepAnchor, end - start)

        cursor.endEditBlock()

    def save(self):
        self.signal_save.emit()

    def isModified(self):
        return self.modified

    def firstVisibleLine(self) -> int:
        return self.firstVisibleBlock().blockNumber()

    def currentLine(self) -> int:
        return self.textCursor().blockNumber()

    def goToLine(self, line: int):
        tc = self.textCursor()
        pos = self.document().findBlockByNumber(line - 1).position()
        tc.setPosition(pos, QTextCursor.MoveAnchor)
        # self.setTextCursor(tc)

    def getSelectedText(self) -> str:
        if self.textCursor().hasSelection():
            return self.textCursor().selectedText()
        else:
            return ''

    def getSelectedRows(self) -> Tuple[int, int]:
        """
        返回选中的行号范围
        :return:
        """
        start = self.textCursor().selectionStart()
        end = self.textCursor().selectionEnd()
        start_block_id = self.document().findBlock(start).blockNumber()
        end_block_id = self.document().findBlock(end).blockNumber()

        return (start_block_id, end_block_id)

    def set_eol_status(self):
        """
        根据文件内容中的换行符设置底部状态

        :return:
        """
        eols = re.findall(r'\r\n|\r|\n', self.toPlainText())
        if not eols:
            print('\\n')
            # self.label_status_eol.setText('Unix(LF)')
            # self.textEdit.setEolMode(QsciScintilla.EolUnix)  # \n换行
            return
        grouped = [(len(list(group)), key) for key, group in groupby(sorted(eols))]
        eol = sorted(grouped, reverse=True)[0][1]
        if eol == '\r\n':
            print('\\r\\n')
            # self.label_status_eol.setText('Windows(CR LF)')
            # self.textEdit.setEolMode(QsciScintilla.EolWindows)  # \r\n换行
            # return QsciScintilla.EolWindows
        if eol == '\r':
            print('\\r')
            # self.label_status_eol.setText('Mac(CR)')
            # self.textEdit.setEolMode(QsciScintilla.EolMac)  # \r换行
            return
        # self.label_status_eol.setText('Unix(LF)')
        # self.textEdit.setEolMode(QsciScintilla.EolUnix)  # \n换行

    def load_color_scheme(self, scheme: Dict[str, str]):
        PythonHighlighter.font_cfg.load_color_scheme(scheme)

    def getCursorPosition(self) -> int:
        # QTextCursor.position()
        return self.textCursor().position()

    def setSelection(self):
        raise NotImplementedError
        text_cursor: QTextCursor = self.textCursor()
        text_cursor.clearSelection()
        # text_cursor.setPosition()

    def hasSelectedText(self):
        return self.textCursor().hasSelection()

    def replace(self, replacement: str):
        cursor: QTextCursor = self.textCursor()
        cursor.removeSelectedText()
        cursor.insertText(replacement)
        # self.textCursor().replace(replacement, self.textCursor())
        self.setTextCursor(cursor)

    def get_word(self, row=-1, col=0) -> str:
        """
        获取某个行列位置下的文本.若row=-1则获取光标之下的文本
        :return:
        """
        if row == -1:
            line_no = self.currentLine()
            text_cursor: QTextCursor = self.textCursor()
            col = text_cursor.positionInBlock()
        else:
            line_no = row
        text: str = self.document().findBlockByLineNumber(line_no).text()

        col_forward = col
        col_backward = col
        seps_set = ' \n,()[]{}\'\";:\t!+-*/\\=.'
        try:
            while 1:
                if col_forward >= 0 and text[col_forward] in seps_set:
                    break
                if col_forward > 0:
                    col_forward -= 1
                else:
                    break
            length = len(text)
            while 1:
                if col_backward < length and text[col_backward] in seps_set:
                    break
                if col_backward < length - 1:
                    col_backward += 1
                else:
                    break
            word = text[col_forward:col_backward + 1].strip(seps_set)
            return word
        except:
            import traceback
            traceback.print_exc()
            return ''

    def register_highlight(self, line: int, start: int, length: int, marker: int, hint: str):
        """
        注册高亮
        :param line: 要高亮的行号
        :param start: 从line行的哪一列开始高亮
        :param length: 高亮区域的长度
        :param marker: 使用的标记颜色等
        :param hint: 使用的提示文字
        :return:
        """
        self.highlighter.registerHighlight(line, start, length, marker, hint)

    def clear_highlight(self):
        """
        清除高亮
        :return:
        """
        self.highlighter.highlight_marks = {}

    def rehighlight(self):
        self.update_request_queue.put(self.UPDATE_CODE_HIGHLIGHT)

if __name__=='__main__':
    app = QApplication([])
    e = PMBaseCodeEdit()
    e.show()
    app.exec_()