"use client"

import { SparklesIcon } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"

export default function Page() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-muted/30 p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle>Frontend is ready</CardTitle>
            <Badge variant="secondary">shadcn/ui</Badge>
          </div>
          <CardDescription>
            Next.js 16 + Tailwind v4 + Base UI primitives. Press{" "}
            <kbd className="rounded border bg-muted px-1 py-0.5 font-mono text-xs">
              d
            </kbd>{" "}
            to toggle dark mode.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="name">Your name</FieldLabel>
              <Input id="name" placeholder="Ada Lovelace" />
              <FieldDescription>
                We&apos;ll use this to personalize your toast.
              </FieldDescription>
            </Field>
          </FieldGroup>
          <Separator className="my-6" />
          <p className="text-sm text-muted-foreground">
            Installed components: <code>button</code>, <code>card</code>,{" "}
            <code>input</code>, <code>label</code>, <code>field</code>,{" "}
            <code>badge</code>, <code>separator</code>, <code>sonner</code>.
          </p>
        </CardContent>
        <CardFooter className="justify-end gap-2">
          <Button
            variant="outline"
            render={
              <a
                href="https://ui.shadcn.com/docs"
                target="_blank"
                rel="noreferrer"
              />
            }
          >
            Docs
          </Button>
          <Button
            onClick={() => {
              const input = document.getElementById("name") as HTMLInputElement | null
              const name = input?.value.trim() || "friend"
              toast.success(`Hello, ${name}!`, {
                description: "Sonner is wired up in the root layout.",
              })
            }}
          >
            <SparklesIcon data-icon="inline-start" />
            Say hello
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
