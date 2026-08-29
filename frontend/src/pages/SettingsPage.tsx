import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Bell, Palette, Languages, KeyRound } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useSettings, type UserSettings } from '@/hooks/use-settings';
import { SUPPORTED_LANGUAGES, type LanguageCode } from '@/i18n';
import { Button } from '@/components/ui/button';
import { ChangePasswordDialog } from '@/components/ChangePasswordDialog';

interface ToggleRow {
  key: keyof UserSettings;
  label: string;
}

const NOTIFICATION_TOGGLES: ToggleRow[] = [
  { key: 'speedAlerts', label: 'Speed alerts' },
  { key: 'offlineAlerts', label: 'Offline alerts' },
  { key: 'maintenanceReminders', label: 'Maintenance reminders' },
];

const APPEARANCE_TOGGLES: ToggleRow[] = [
  { key: 'autoRefreshMap', label: 'Auto-refresh map' },
  { key: 'speedInMph', label: 'Show speed in mph' },
];

export default function SettingsPage() {
  const { t, i18n } = useTranslation();
  const [changingPassword, setChangingPassword] = useState(false);
  const { settings, updateSetting } = useSettings();
  const currentLanguage = (i18n.resolvedLanguage ?? i18n.language) as LanguageCode;

  return (
    <div className="space-y-6 animate-fade-in max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Manage your account and preferences</p>
      </div>

      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-5 w-5" /> {t('settings.security')}
          </CardTitle>
          <CardDescription>{t('settings.securityDescription')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => setChangingPassword(true)}>
            {t('auth.changePassword')}
          </Button>
        </CardContent>
      </Card>

      <ChangePasswordDialog open={changingPassword} onOpenChange={setChangingPassword} />

      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Bell className="h-5 w-5" /> Notifications</CardTitle>
          <CardDescription>Configure how you receive alerts</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {NOTIFICATION_TOGGLES.map(({ key, label }) => (
            <div key={key} className="flex items-center justify-between">
              <Label htmlFor={key}>{label}</Label>
              <Switch
                id={key}
                checked={settings[key]}
                onCheckedChange={(checked) => updateSetting(key, checked)}
              />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Palette className="h-5 w-5" /> Appearance</CardTitle>
          <CardDescription>Customize the interface</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {APPEARANCE_TOGGLES.map(({ key, label }) => (
            <div key={key} className="flex items-center justify-between">
              <Label htmlFor={key}>{label}</Label>
              <Switch
                id={key}
                checked={settings[key]}
                onCheckedChange={(checked) => updateSetting(key, checked)}
              />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Languages className="h-5 w-5" /> Language</CardTitle>
          <CardDescription>Choose your preferred language</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="language">Display language</Label>
            <Select
              value={currentLanguage}
              onValueChange={(value) => void i18n.changeLanguage(value)}
            >
              <SelectTrigger id="language" className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SUPPORTED_LANGUAGES.map((lang) => (
                  <SelectItem key={lang.code} value={lang.code}>
                    {lang.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
