import { Label } from '@soopa/ui/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@soopa/ui/components/ui/select';
import { useEffect, useState } from 'react';

interface CronBuilderProps {
  value: string;
  onChange: (cronString: string) => void;
}

export function CronBuilder({ value, onChange }: CronBuilderProps) {
  // Parse initial value (defaults to '0 * * * *' if invalid)
  const parts = value.split(' ');
  // If 5 parts, prepend '0' for seconds. If 6 parts, use as is. Otherwise default 6 parts.
  const initial =
    parts.length === 6
      ? parts
      : parts.length === 5
        ? ['0', ...parts]
        : ['0', '0', '*', '*', '*', '*'];

  const [second, setSecond] = useState(initial[0]);
  const [minute, setMinute] = useState(initial[1]);
  const [hour, setHour] = useState(initial[2]);
  const [dayOfMonth, setDayOfMonth] = useState(initial[3]);
  const [month, setMonth] = useState(initial[4]);
  const [dayOfWeek, setDayOfWeek] = useState(initial[5]);

  useEffect(() => {
    onChange(`${second} ${minute} ${hour} ${dayOfMonth} ${month} ${dayOfWeek}`);
  }, [second, minute, hour, dayOfMonth, month, dayOfWeek, onChange]);

  const generateOptions = (start: number, end: number, labelPrefix = '') => {
    const opts = [{ value: '*', label: 'Every' }];
    for (let i = start; i <= end; i++) {
      opts.push({ value: String(i), label: `${labelPrefix}${i}` });
    }
    return opts;
  };

  const seconds = generateOptions(0, 59);
  const minutes = generateOptions(0, 59);
  const hours = generateOptions(0, 23);
  const daysOfMonth = generateOptions(1, 31);
  const months = [
    { value: '*', label: 'Every' },
    { value: '1', label: 'January' },
    { value: '2', label: 'February' },
    { value: '3', label: 'March' },
    { value: '4', label: 'April' },
    { value: '5', label: 'May' },
    { value: '6', label: 'June' },
    { value: '7', label: 'July' },
    { value: '8', label: 'August' },
    { value: '9', label: 'September' },
    { value: '10', label: 'October' },
    { value: '11', label: 'November' },
    { value: '12', label: 'December' },
  ];
  const daysOfWeek = [
    { value: '*', label: 'Every' },
    { value: '0', label: 'Sunday' },
    { value: '1', label: 'Monday' },
    { value: '2', label: 'Tuesday' },
    { value: '3', label: 'Wednesday' },
    { value: '4', label: 'Thursday' },
    { value: '5', label: 'Friday' },
    { value: '6', label: 'Saturday' },
  ];

  return (
    <div className="grid grid-cols-6 gap-4">
      <div className="space-y-2">
        <Label className="text-xs">Second</Label>
        <Select value={second} onValueChange={setSecond}>
          <SelectTrigger>
            <SelectValue placeholder="Second" />
          </SelectTrigger>
          <SelectContent>
            {seconds.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label className="text-xs">Minute</Label>
        <Select value={minute} onValueChange={setMinute}>
          <SelectTrigger>
            <SelectValue placeholder="Minute" />
          </SelectTrigger>
          <SelectContent>
            {minutes.map((m) => (
              <SelectItem key={m.value} value={m.value}>
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label className="text-xs">Hour</Label>
        <Select value={hour} onValueChange={setHour}>
          <SelectTrigger>
            <SelectValue placeholder="Hour" />
          </SelectTrigger>
          <SelectContent>
            {hours.map((h) => (
              <SelectItem key={h.value} value={h.value}>
                {h.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label className="text-xs">Day of Month</Label>
        <Select value={dayOfMonth} onValueChange={setDayOfMonth}>
          <SelectTrigger>
            <SelectValue placeholder="Day" />
          </SelectTrigger>
          <SelectContent>
            {daysOfMonth.map((d) => (
              <SelectItem key={d.value} value={d.value}>
                {d.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label className="text-xs">Month</Label>
        <Select value={month} onValueChange={setMonth}>
          <SelectTrigger>
            <SelectValue placeholder="Month" />
          </SelectTrigger>
          <SelectContent>
            {months.map((m) => (
              <SelectItem key={m.value} value={m.value}>
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label className="text-xs">Day of Week</Label>
        <Select value={dayOfWeek} onValueChange={setDayOfWeek}>
          <SelectTrigger>
            <SelectValue placeholder="Weekday" />
          </SelectTrigger>
          <SelectContent>
            {daysOfWeek.map((d) => (
              <SelectItem key={d.value} value={d.value}>
                {d.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
