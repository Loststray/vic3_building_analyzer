现在需要新增功能，要求如下：

所有txt文件的顶层对象可能出现4个前缀修饰符： REPLACE: , TRY_REPLACE: , INJECT: , TRY_INJECT: ，如果没有前缀则默认为 INSERT: 以下为不同前缀修饰符的作用

- INSERT: 插入对象，如果对象已存在则报错
- REPLACE: && TRY_REPLACE: 如果存在同名对象，删除同名对象并且用当前的对象替换;否则报错
- INJECT: && TRT_INJECT: 如果存在同名对象，将当前的对象与已有对象进行合并，合并过程中相同的成员也需要一起合并;否则报错


以下为 INJECT: 示例

```
building_test = {
	production_method_groups = {
		pmg_base_building_cotton_plantation
		pmg_cotton_exploitation
		pmg_train_automation_building_cotton_plantation
	}
}

INJECT:building_test = {
	production_method_groups = {
		pmg_gizmo_waterwrangler_irrigation_cotton
	}
}
```

等价于

```
building_test = {
	production_method_groups = {
		pmg_base_building_cotton_plantation
		pmg_cotton_exploitation
		pmg_train_automation_building_cotton_plantation
		pmg_gizmo_waterwrangler_irrigation_cotton
	}
}
```

以下为 REPLACE: 示例

```
building_test = {
	production_method_groups = {
		pmg_base_building_cotton_plantation
		pmg_cotton_exploitation
		pmg_train_automation_building_cotton_plantation
	}
}

REPLACE:building_test = {
	production_method_groups = {
		pmg_gizmo_waterwrangler_irrigation_cotton
	}
}
```

等价于

```
building_test = {
	production_method_groups = {
		pmg_gizmo_waterwrangler_irrigation_cotton
	}
}
```