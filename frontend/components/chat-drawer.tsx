"use client"

import * as React from "react"
import {
  LoaderIcon,
  MessageSquareTextIcon,
  SendIcon,
  SparklesIcon,
  UserIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"
import type { ChatMessage, PredictResponse } from "@/lib/types"
import { cn } from "@/lib/utils"

// Pre-canned prompts that surface the most useful questions a store manager
// would actually ask. They change based on the urgency so the suggestions
// stay relevant.
function suggestedQuestions(decision: PredictResponse | null): string[] {
  if (!decision) return []
  const base = ["Walk me through the math.", "What if it weren't peak hour?"]
  if (decision.urgency === "HIGH") {
    return [
      "Why is this HIGH urgency?",
      `Is ${decision.restock} units overkill?`,
      "What would downgrade it to MEDIUM?",
    ]
  }
  if (decision.urgency === "MEDIUM") {
    return [
      "Why MEDIUM and not HIGH?",
      "When does this tip into HIGH?",
      ...base,
    ]
  }
  return [
    "Why are we flagging this at all?",
    "What would force a restock?",
    ...base,
  ]
}

export function ChatDrawer({
  decision,
  disabled,
}: {
  decision: PredictResponse | null
  disabled?: boolean
}) {
  const [open, setOpen] = React.useState(false)
  const [messages, setMessages] = React.useState<ChatMessage[]>([])
  const [draft, setDraft] = React.useState("")
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const scrollRef = React.useRef<HTMLDivElement>(null)

  // Reset the conversation whenever the underlying decision changes — the
  // operator is now looking at a different SKU, so old Q&A is irrelevant.
  const decisionKey = decision ? `${decision.item_id}-${decision.hour}` : null
  React.useEffect(() => {
    setMessages([])
    setError(null)
  }, [decisionKey])

  // Auto-scroll to the bottom whenever the message list grows.
  React.useEffect(() => {
    const node = scrollRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages, loading])

  async function send(question: string) {
    const trimmed = question.trim()
    if (!trimmed || !decision || loading) return

    const nextHistory: ChatMessage[] = [
      ...messages,
      { role: "user", content: trimmed },
    ]
    setMessages(nextHistory)
    setDraft("")
    setLoading(true)
    setError(null)

    try {
      const res = await api.chat(decision, trimmed, messages)
      setMessages([
        ...nextHistory,
        { role: "assistant", content: res.reply },
      ])
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not reach the reasoning service."
      )
    } finally {
      setLoading(false)
    }
  }

  const suggestions = suggestedQuestions(decision)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={
          <Button
            size="lg"
            className="fixed bottom-6 right-6 z-40 gap-2 rounded-full px-5 shadow-lg"
            disabled={disabled || !decision}
            aria-label="Open reasoning chat"
          />
        }
      >
        <MessageSquareTextIcon />
        Ask the AI
      </SheetTrigger>

      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 p-0 sm:max-w-md"
      >
        <SheetHeader className="border-b border-border/60 bg-muted/30 p-5">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <SparklesIcon className="size-4" />
            </div>
            <div className="flex flex-col">
              <SheetTitle className="text-base">Reasoning chat</SheetTitle>
              <SheetDescription className="text-xs">
                {decision
                  ? `Grounded on ${decision.item_name} · ${decision.day_of_week} ${decision.hour}:00`
                  : "Waiting for a decision to reason over"}
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-5 py-4"
        >
          {messages.length === 0 && !loading && (
            <EmptyState
              decision={decision}
              suggestions={suggestions}
              onPick={send}
            />
          )}

          <div className="flex flex-col gap-4">
            {messages.map((m, i) => (
              <MessageBubble key={i} message={m} />
            ))}
            {loading && <ThinkingBubble />}
          </div>

          {error && (
            <div className="mt-4 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
        </div>

        <div className="border-t border-border/60 bg-muted/20 p-4">
          <div className="flex items-end gap-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  void send(draft)
                }
              }}
              placeholder={
                decision
                  ? "Ask why, what-if, or push back…"
                  : "Pick an alert first"
              }
              className="min-h-[44px] resize-none"
              disabled={!decision || loading}
              rows={1}
            />
            <Button
              size="icon"
              onClick={() => void send(draft)}
              disabled={!decision || !draft.trim() || loading}
              aria-label="Send"
            >
              {loading ? (
                <LoaderIcon className="animate-spin" />
              ) : (
                <SendIcon />
              )}
            </Button>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Enter to send · Shift+Enter for newline
          </p>
        </div>
      </SheetContent>
    </Sheet>
  )
}

function EmptyState({
  decision,
  suggestions,
  onPick,
}: {
  decision: PredictResponse | null
  suggestions: string[]
  onPick: (q: string) => void
}) {
  return (
    <div className="flex flex-col items-start gap-4 py-6">
      <div className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-primary">
        <SparklesIcon className="size-5" />
      </div>
      <div>
        <h3 className="text-sm font-semibold">
          Ask anything about this decision
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          {decision
            ? `Grounded on real numbers: predicted ${decision.predicted_velocity} u/hr, adjusted ${decision.adjusted_velocity} u/hr, coverage ${decision.coverage_hours}h.`
            : "Select a SKU alert to start."}
        </p>
      </div>
      {suggestions.length > 0 && (
        <div className="flex flex-col gap-2 self-stretch">
          {suggestions.map((q) => (
            <button
              key={q}
              onClick={() => onPick(q)}
              className="rounded-md border border-border/70 bg-background/80 px-3 py-2 text-left text-sm transition-colors hover:border-primary/40 hover:bg-primary/5"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user"
  return (
    <div
      className={cn(
        "flex items-start gap-2.5",
        isUser && "flex-row-reverse"
      )}
    >
      <div
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-primary/10 text-primary"
        )}
      >
        {isUser ? (
          <UserIcon className="size-3.5" />
        ) : (
          <SparklesIcon className="size-3.5" />
        )}
      </div>
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted/70 text-foreground"
        )}
      >
        {message.content}
      </div>
    </div>
  )
}

function ThinkingBubble() {
  return (
    <div className="flex items-start gap-2.5">
      <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <SparklesIcon className="size-3.5" />
      </div>
      <div className="flex items-center gap-1.5 rounded-2xl bg-muted/70 px-3.5 py-3">
        <Badge variant="outline" className="gap-1.5">
          <LoaderIcon className="size-3 animate-spin" />
          <span className="text-[11px]">thinking…</span>
        </Badge>
      </div>
    </div>
  )
}
