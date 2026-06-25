import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';

import { ApiError } from '../lib/api';
import { meApi, type Expense, type ExpenseCategory } from '../lib/me';
import { formatDate } from '../lib/format';
import { palette, radius, spacing, typography } from '../theme/theme';
import { Screen } from '../components/Screen';
import {
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Loading,
  SectionHeader,
} from '../components/ui';

const CATEGORIES: { key: ExpenseCategory; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: 'food', icon: 'fast-food-outline' },
  { key: 'toll', icon: 'card-outline' },
  { key: 'parking', icon: 'car-outline' },
  { key: 'fine', icon: 'warning-outline' },
  { key: 'repair', icon: 'build-outline' },
  { key: 'lodging', icon: 'bed-outline' },
  { key: 'customs', icon: 'document-text-outline' },
  { key: 'other', icon: 'ellipsis-horizontal-outline' },
];

const CATEGORY_ICON: Record<ExpenseCategory, keyof typeof Ionicons.glyphMap> = Object.fromEntries(
  CATEGORIES.map((c) => [c.key, c.icon]),
) as Record<ExpenseCategory, keyof typeof Ionicons.glyphMap>;

export function ExpensesScreen() {
  const { t } = useTranslation();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [noTruck, setNoTruck] = useState(false);
  const [expenses, setExpenses] = useState<Expense[]>([]);

  const [category, setCategory] = useState<ExpenseCategory>('food');
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setNoTruck(false);
    try {
      setExpenses(await meApi.expenses());
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const monthTotal = useMemo(() => {
    const now = new Date();
    return expenses
      .filter((e) => {
        const d = new Date(e.spent_at);
        return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
      })
      .reduce((sum, e) => sum + Number(e.amount ?? 0), 0);
  }, [expenses]);

  const canSubmit = Number(amount) > 0 && !busy;

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      await meApi.addExpense({
        category,
        amount: Number(amount),
        note: note.trim() || null,
      });
      setAmount('');
      setNote('');
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setNoTruck(true);
      else Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setBusy(false);
    }
  }, [canSubmit, category, amount, note, load, t]);

  const confirmDelete = useCallback(
    (item: Expense) => {
      Alert.alert(t('expenses.deleteTitle'), t('expenses.deleteBody'), [
        { text: t('common.cancel'), style: 'cancel' },
        {
          text: t('common.delete'),
          style: 'destructive',
          onPress: async () => {
            try {
              await meApi.deleteExpense(item.id);
              setExpenses((prev) => prev.filter((e) => e.id !== item.id));
            } catch (e) {
              Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
            }
          },
        },
      ]);
    },
    [t],
  );

  if (loading) return <Loading />;

  return (
    <Screen
      eyebrow={t('app.name')}
      title={t('expenses.title')}
      subtitle={
        expenses.length
          ? `${t('expenses.thisMonth')}: ${monthTotal.toLocaleString()} · ${expenses.length}`
          : undefined
      }
      icon="wallet"
      refreshing={refreshing}
      onRefresh={() => {
        setRefreshing(true);
        load();
      }}
    >
      {noTruck && <ErrorBox message={t('home.noTruck')} />}

      <Card>
        <SectionHeader
          icon="add-circle"
          title={t('expenses.addExpense')}
          color={palette.expense}
          bg={palette.expenseBg}
        />

        <Text style={styles.pickerLabel}>{t('expenses.category')}</Text>
        <View style={styles.categoryGrid}>
          {CATEGORIES.map((c) => {
            const active = c.key === category;
            return (
              <Pressable
                key={c.key}
                onPress={() => setCategory(c.key)}
                style={[styles.catChip, active && styles.catChipActive]}
              >
                <Ionicons
                  name={c.icon}
                  size={16}
                  color={active ? palette.white : palette.expense}
                />
                <Text style={[styles.catChipText, active && styles.catChipTextActive]}>
                  {t(`expenses.cat.${c.key}`)}
                </Text>
              </Pressable>
            );
          })}
        </View>

        <Field
          label={t('expenses.amount')}
          icon="cash-outline"
          value={amount}
          onChangeText={setAmount}
          keyboardType="numeric"
          placeholder="0"
        />
        <Field
          label={t('expenses.note')}
          icon="create-outline"
          value={note}
          onChangeText={setNote}
          placeholder="—"
        />
        <Button
          label={t('expenses.save')}
          icon="save-outline"
          onPress={submit}
          disabled={!canSubmit}
          loading={busy}
        />
      </Card>

      <Card>
        <SectionHeader
          icon="time"
          title={t('expenses.history')}
          color={palette.expense}
          bg={palette.expenseBg}
        />
        {expenses.length === 0 ? (
          <EmptyState icon="wallet-outline" title={t('expenses.empty')} />
        ) : (
          expenses.map((item) => (
            <Pressable
              key={item.id}
              onLongPress={() => confirmDelete(item)}
              style={styles.logItem}
            >
              <View style={styles.logIcon}>
                <Ionicons name={CATEGORY_ICON[item.category]} size={18} color={palette.expense} />
              </View>
              <View style={styles.logBody}>
                <Text style={styles.logTitle}>{t(`expenses.cat.${item.category}`)}</Text>
                <Text style={styles.logMeta}>
                  {formatDate(item.spent_at)}
                  {item.note ? ` · ${item.note}` : ''}
                </Text>
              </View>
              <Text style={styles.logCost}>{Number(item.amount).toLocaleString()}</Text>
            </Pressable>
          ))
        )}
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  pickerLabel: { ...typography.label, marginBottom: spacing.sm },
  categoryGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  catChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: radius.pill,
    backgroundColor: palette.expenseBg,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  catChipActive: { backgroundColor: palette.expense, borderColor: palette.expense },
  catChipText: { ...typography.label, color: palette.expense },
  catChipTextActive: { color: palette.white },
  logItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderTopWidth: 1,
    borderTopColor: palette.line,
    paddingTop: spacing.md,
  },
  logIcon: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    backgroundColor: palette.expenseBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logBody: { flex: 1, gap: 2 },
  logTitle: { ...typography.body, color: palette.ink, fontWeight: '700' },
  logMeta: typography.caption,
  logCost: { ...typography.heading, color: palette.ink },
});
