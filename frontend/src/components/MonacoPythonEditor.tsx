import React, { useEffect, useRef } from "react";
import Editor, { OnMount, loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";

// Use local monaco-editor package to guarantee reliable offline rendering without external CDN calls
loader.config({ monaco });

import { SyntaxErrorInfo } from "../types/ast";

interface MonacoPythonEditorProps {
  code: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  syntaxError?: SyntaxErrorInfo | { lineno?: number | null; offset?: number | null; col_offset?: number | null; message: string } | null;
  height?: string;
  onRun?: () => void;
  targetLine?: number | null;
}

export const MonacoPythonEditor: React.FC<MonacoPythonEditorProps> = ({
  code,
  onChange,
  readOnly = false,
  syntaxError = null,
  height = "320px",
  onRun,
  targetLine = null,
}) => {
  const editorRef = useRef<any>(null);
  const monacoRef = useRef<any>(null);

  const handleEditorDidMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    // Register Ctrl+Enter / Cmd+Enter to run analysis directly from editor
    if (onRun) {
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
        onRun();
      });
    }

    // Apply diagnostics if already present upon mount
    if (syntaxError) {
      applySyntaxMarkers(editor, monaco, syntaxError);
    }
  };

  const applySyntaxMarkers = (
    editor: any,
    monaco: any,
    err: SyntaxErrorInfo | { lineno?: number | null; offset?: number | null; col_offset?: number | null; message: string }
  ) => {
    const model = editor.getModel();
    if (!model) return;

    const line = err.lineno || 1;
    const col = ('col_offset' in err && err.col_offset != null ? err.col_offset : ('offset' in err && err.offset != null ? err.offset : 1));

    monaco.editor.setModelMarkers(model, "apicompass_syntax", [
      {
        startLineNumber: line,
        startColumn: col,
        endLineNumber: line,
        endColumn: col + 15,
        message: `Static AST Syntax Error: ${err.message}`,
        severity: monaco.MarkerSeverity.Error,
      },
    ]);
  };

  const clearSyntaxMarkers = () => {
    if (editorRef.current && monacoRef.current) {
      const model = editorRef.current.getModel();
      if (model) {
        monacoRef.current.editor.setModelMarkers(model, "apicompass_syntax", []);
      }
    }
  };

  // Sync syntax markers whenever syntaxError prop changes
  useEffect(() => {
    if (editorRef.current && monacoRef.current) {
      if (syntaxError) {
        applySyntaxMarkers(editorRef.current, monacoRef.current, syntaxError);
      } else {
        clearSyntaxMarkers();
      }
    }
  }, [syntaxError]);

  // Jump to targetLine when clicked from a finding
  useEffect(() => {
    if (editorRef.current && targetLine != null && targetLine > 0) {
      editorRef.current.revealLineInCenter(targetLine);
      editorRef.current.setPosition({ lineNumber: targetLine, column: 1 });
      editorRef.current.focus();
    }
  }, [targetLine]);

  return (
    <div
      className="relative flex-1 w-full bg-[#0d1117] overflow-hidden"
      data-testid="monaco-code-editor-container"
      aria-label="Python Code Editor"
    >
      <Editor
        height={height}
        language="python"
        theme="vs-dark"
        value={code}
        onChange={(val) => {
          onChange(val || "");
          if (syntaxError) {
            clearSyntaxMarkers();
          }
        }}
        onMount={handleEditorDidMount}
        loading={
          <div className="flex items-center justify-center h-full text-xs text-slate-400 bg-slate-950/80">
            <span>Loading Monaco Editor...</span>
          </div>
        }
        options={{
          readOnly,
          minimap: { enabled: false },
          fontSize: 13,
          lineHeight: 20,
          lineNumbers: "on",
          lineNumbersMinChars: 3,
          scrollBeyondLastLine: false,
          automaticLayout: true,
          matchBrackets: "always",
          renderLineHighlight: "all",
          folding: true,
          tabSize: 4,
          insertSpaces: true,
          wordWrap: "on",
          fixedOverflowWidgets: true,
          fontFamily:
            "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
        }}
      />
    </div>
  );
};
