"use client"

import * as React from "react"
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react"
import { 
  format, 
  addMonths, 
  subMonths, 
  startOfMonth, 
  endOfMonth, 
  startOfWeek, 
  endOfWeek, 
  isSameMonth, 
  isSameDay, 
  eachDayOfInterval 
} from "date-fns"
import { it } from "date-fns/locale"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

export interface CalendarProps {
  selected?: Date
  onSelect?: (date: Date) => void
  className?: string
}

export function Calendar({ selected, onSelect, className }: CalendarProps) {
  const [currentMonth, setCurrentMonth] = React.useState(selected || new Date())

  const nextMonth = () => setCurrentMonth(addMonths(currentMonth, 1))
  const prevMonth = () => setCurrentMonth(subMonths(currentMonth, 1))

  const monthStart = startOfMonth(currentMonth)
  const monthEnd = endOfMonth(monthStart)
  const startDate = startOfWeek(monthStart, { weekStartsOn: 1 })
  const endDate = endOfWeek(monthEnd, { weekStartsOn: 1 })

  const calendarDays = eachDayOfInterval({
    start: startDate,
    end: endDate,
  })

  const weekDays = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]

  return (
    <div className={cn("p-3 w-fit bg-popover rounded-xl", className)}>
      <div className="flex items-center justify-between mb-4 px-1">
        <h2 className="text-sm font-semibold capitalize">
          {format(currentMonth, "MMMM yyyy", { locale: it })}
        </h2>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={prevMonth}
            className="hover:bg-accent"
          >
            <ChevronLeftIcon className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={nextMonth}
            className="hover:bg-accent"
          >
            <ChevronRightIcon className="size-4" />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-1 mb-2">
        {weekDays.map((day) => (
          <div
            key={day}
            className="text-[10px] font-bold text-center text-muted-foreground uppercase py-1"
          >
            {day}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-1">
        {calendarDays.map((day, idx) => {
          const isSelected = selected && isSameDay(day, selected)
          const isCurrentMonth = isSameMonth(day, monthStart)
          const isToday = isSameDay(day, new Date())

          return (
            <button
              key={idx}
              onClick={() => onSelect?.(day)}
              className={cn(
                "size-8 flex items-center justify-center rounded-lg text-xs transition-all",
                !isCurrentMonth && "text-muted-foreground/30",
                isCurrentMonth && !isSelected && "text-foreground hover:bg-accent",
                isSelected && "bg-primary text-primary-foreground font-bold shadow-sm scale-105",
                isToday && !isSelected && "ring-1 ring-primary/30 text-primary font-bold"
              )}
            >
              {format(day, "d")}
            </button>
          )
        })}
      </div>
    </div>
  )
}
