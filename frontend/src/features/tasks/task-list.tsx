import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { ActionList, ProgressBar } from "@primer/react";
import {
  CircleIcon,
  CheckCircleIcon,
  CircleSlashIcon,
  ClockIcon,
  DotFillIcon,
} from "@primer/octicons-react";
import { taskStatuses, type Task, type TaskStatus } from "./task-api";

export const taskStatusIcons = {
  backlog: DotFillIcon,
  todo: CircleIcon,
  in_progress: ClockIcon,
  blocked: CircleSlashIcon,
  done: CheckCircleIcon,
};

export function TaskList({
  tasks,
  href,
  showOpportunity = false,
  showProgress = false,
}: {
  tasks: Task[];
  href: (task: Task) => string;
  showOpportunity?: boolean;
  showProgress?: boolean;
}) {
  if (!tasks.length)
    return <p className="text-sm text-muted-foreground">No tasks yet.</p>;

  const done = tasks.filter((task) => task.status === "done").length;
  return (
    <div>
      {showProgress && (
        <div className="mb-3 space-y-2">
          <p className="text-sm text-muted-foreground">
            {done === tasks.length
              ? "All tasks complete"
              : `${done} of ${tasks.length} done`}
          </p>
          <ProgressBar
            progress={(done / tasks.length) * 100}
            aria-label="Task completion"
          />
        </div>
      )}
      <ActionList aria-label="Tasks">
        {tasks.map((task) => {
          const Icon = taskStatusIcons[task.status];
          return (
            <ActionList.LinkItem key={task.id} href={href(task)}>
              <ActionList.LeadingVisual>
                <Icon />
              </ActionList.LeadingVisual>
              {task.title}
              {showOpportunity && (
                <ActionList.Description>
                  {task.opportunity_name}
                </ActionList.Description>
              )}
              <ActionList.TrailingVisual>
                {taskStatuses[task.status]}
              </ActionList.TrailingVisual>
            </ActionList.LinkItem>
          );
        })}
      </ActionList>
    </div>
  );
}

export function TaskStatusSelect({
  status,
  label,
  disabled,
  onChange,
}: {
  status: TaskStatus;
  label: string;
  disabled?: boolean;
  onChange: (status: TaskStatus) => void;
}) {
  const Icon = taskStatusIcons[status];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={label}
          disabled={disabled}
          className="inline-flex items-center gap-2 rounded-full text-sm text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
        >
          <Icon size={16} />
          {taskStatuses[status]}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {Object.entries(taskStatuses).map(([value, name]) => {
          const OptionIcon = taskStatusIcons[value as TaskStatus];
          return (
            <DropdownMenuItem
              key={value}
              disabled={value === status}
              onSelect={() => onChange(value as TaskStatus)}
            >
              <OptionIcon size={16} />
              {name}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
