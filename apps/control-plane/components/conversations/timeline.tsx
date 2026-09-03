import type { TimelineMessage } from "../../lib/conversations";

export function Timeline({ messages }: { messages: TimelineMessage[] }) {
  return (
    <ol className="conversation-timeline">
      {messages.map((message) => (
        <li className={`timeline-${message.sender_type}`} key={message.id}>
          <header>
            <strong>{sender(message.sender_type)}</strong>
            <time dateTime={message.occurred_at}>
              {new Date(message.occurred_at).toLocaleString()}
            </time>
          </header>
          <p>{message.text}</p>
        </li>
      ))}
    </ol>
  );
}

function sender(value: string): string {
  return (
    { customer: "Customer", ai: "AI agent", human: "Human", system: "System" }[
      value
    ] ?? value
  );
}
